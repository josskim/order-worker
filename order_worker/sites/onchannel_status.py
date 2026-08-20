from __future__ import annotations

import asyncio
from typing import Any

from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.onchannel import ACCOUNTS
from order_worker.sites.status_utils import ProductNotFound, failed, normalize, option_matches, product_not_found

SITE = "온채널"
SITE_CODE = "onchannel"
LOGIN_URL = "https://www.onch3.co.kr/login/login_web.php"
MANAGEMENT_URL = "https://www.onch3.co.kr/products_management.php"


async def _login(page: Page, account) -> None:
    _, user_id, password, _ = account
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await page.fill('input[name="username"]', user_id)
    await page.fill('input[name="password"]', password)
    await page.click("button.submit-btn")
    await page.wait_for_url(lambda url: "/login/" not in url, timeout=30000)


async def _search(page: Page, product_code: str):
    await page.goto(MANAGEMENT_URL, wait_until="networkidle")
    await page.locator('select[name="search_type"]').first.select_option("product_name")
    await page.locator('input[name="search_text"]').first.fill(product_code)
    await page.locator("#searchForm button[type=submit]").click()
    await page.wait_for_load_state("networkidle")
    rows = page.locator("table tbody tr").filter(has_text=product_code)
    exact = []
    for index in range(await rows.count()):
        row = rows.nth(index)
        if normalize(product_code) in normalize(await row.inner_text()):
            exact.append(row)
    if len(exact) == 0:
        raise ProductNotFound(product_code)
    if len(exact) != 1:
        raise RuntimeError(f"{SITE}: 상품코드 {product_code} 검색 결과가 {len(exact)}건이라 처리하지 않았습니다.")
    return exact[0]


async def _option(page: Page, row, option_name: str, preview: bool, restock: bool = False) -> dict[str, Any]:
    await row.locator(".btn-op-status").click()
    modal = page.locator(".modal:visible")
    await modal.wait_for()
    option_rows = modal.locator("tbody tr")
    matches = []
    for index in range(await option_rows.count()):
        candidate = option_rows.nth(index)
        lines = [line.strip() for line in (await candidate.inner_text()).splitlines() if line.strip()]
        text = lines[0] if lines else ""
        if option_matches(option_name, text):
            matches.append((candidate, text))
    if len(matches) != 1:
        raise RuntimeError(f"{SITE}: 옵션명 '{option_name}'을 1건으로 찾지 못해 처리하지 않았습니다. (일치 {len(matches)}건)")
    target, label = matches[0]
    status = target.locator('select[name="saleStatusSelect"]')
    wanted = "1" if restock else "3"
    if await status.input_value() == wanted:
        return {"success": True, "alreadyProcessed": True, "matchedOption": label, "verified": True}
    if preview:
        return {"success": True, "preview": True, "matchedOption": label}
    await target.locator('input[name="optionCheckbox"]').check()
    await status.select_option(wanted)
    await modal.locator("#optionReasonTextarea").fill(".")
    await modal.locator("#selectCompleteButton").click()
    await page.wait_for_timeout(1600)
    return {"success": True, "matchedOption": label, "verified": True}


async def _product(page: Page, row, preview: bool, restock: bool = False) -> dict[str, Any]:
    is_soldout = "품절" in await row.inner_text()
    if is_soldout != restock:
        return {"success": True, "alreadyProcessed": True, "verified": True}
    if preview:
        return {"success": True, "preview": True}
    await row.locator(".btn-individual-sale-status").click()
    modal = page.locator(".modal:visible")
    await modal.locator("#saleStatusSelect").select_option("1" if restock else "5")
    await modal.locator("#reasonTextarea").fill(".")
    await modal.locator("#submitSaleStatus").click()
    await page.wait_for_timeout(1600)
    return {"success": True, "verified": True}


async def run(action: str, product_code: str, option_name: str | None = None, preview: bool = False, account_code: str = "onch3") -> dict[str, Any]:
    account = next((item for item in ACCOUNTS if item[0] == account_code), None)
    if account is None:
        raise ValueError(f"지원하지 않는 온채널 계정입니다: {account_code}")
    site_code, _, _, site = account
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=config.HEADLESS)
        page = await browser.new_page()
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        try:
            await _login(page, account)
            row = await _search(page, product_code)
            restock = action.endswith("restock")
            result = await _option(page, row, option_name or "", preview, restock) if action.startswith("option-") else await _product(page, row, preview, restock)
            return {"site": site, "siteCode": site_code, "action": action, "productCode": product_code, **result}
        except ProductNotFound:
            return product_not_found(site, site_code, action, product_code)
        except Exception as exc:
            return failed(site, site_code, action, product_code, exc)
        finally:
            await browser.close()
