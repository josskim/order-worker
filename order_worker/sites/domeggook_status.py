from __future__ import annotations

import asyncio
from typing import Any

from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.domeggook import ACCOUNTS
from order_worker.sites.status_utils import failed, normalize, option_matches

SITE = "도매꾹"
SITE_CODE = "domeggook"
LOGIN_URL = "https://domeggook.com/ssl/member/mem_loginForm.php"
MANAGEMENT_URL = "https://www.domeggook.com/sc/item/lstAll"


async def _login(page: Page) -> None:
    _, user_id, password, _ = ACCOUNTS[0]
    await page.goto(LOGIN_URL)
    await page.fill("#idInput", user_id)
    await page.fill("#pwInput", password)
    await page.click("#formLogin > input.formSubmit")
    await page.wait_for_load_state("networkidle")


async def _search(page: Page, product_code: str) -> str:
    await page.goto(MANAGEMENT_URL, wait_until="networkidle")
    await page.locator('input[name="ttl"]').fill(product_code)
    await page.locator('input[type="submit"]').click()
    await page.wait_for_timeout(1800)
    cells = page.locator('td[data-column-name="code"]').filter(has_text=product_code)
    if await cells.count() != 1 or normalize(await cells.first.inner_text()) != normalize(product_code):
        raise RuntimeError(f"{SITE}: 상품코드 {product_code} 검색 결과를 1건으로 확인하지 못해 처리하지 않았습니다.")
    return await cells.first.get_attribute("data-row-key") or "0"


async def _option(page: Page, row_key: str, option_name: str, preview: bool) -> dict[str, Any]:
    await page.locator('.tui-grid-rside-area .tui-grid-body-area').evaluate("e => e.scrollLeft = 800")
    await page.wait_for_timeout(400)
    cell = page.locator(f'td[data-row-key="{row_key}"][data-column-name="useOpt"]')
    if await cell.count() != 1:
        raise RuntimeError(f"{SITE}: 주문옵션 사용여부 칸을 찾지 못했습니다.")
    async with page.expect_popup() as popup_info:
        await cell.locator("a").click()
    popup = await popup_info.value
    await popup.wait_for_load_state("domcontentloaded")
    option_names = await popup.locator('input[name="optValue[]"]').evaluate_all("es => es.map(e => e.value.split(','))")
    labels = []
    if len(option_names) == 1:
        labels = option_names[0]
    elif len(option_names) >= 2:
        labels = [f"{first}/{second}" for first in option_names[0] for second in option_names[1]]
    matches = [index for index, label in enumerate(labels) if option_matches(option_name, label)]
    if len(matches) != 1:
        raise RuntimeError(f"{SITE}: 옵션명 '{option_name}'을 1건으로 찾지 못해 처리하지 않았습니다. (일치 {len(matches)}건)")
    index = matches[0]
    qty = popup.locator('input[name="qty[]"]').nth(index)
    status = popup.locator('select[name="hid[]"]').nth(index)
    if await qty.input_value() == "0" and await status.input_value() == "1":
        return {"success": True, "alreadyProcessed": True, "matchedOption": labels[index], "verified": True}
    if preview:
        return {"success": True, "preview": True, "matchedOption": labels[index]}
    await popup.locator('input[name="optSel[]"]').nth(index).check()
    await qty.fill("0")
    await status.select_option("1")
    save = popup.locator('img[onclick*="endOptSet"]')
    if await save.count() == 0:
        raise RuntimeError(f"{SITE}: 옵션 저장 버튼을 찾지 못했습니다.")
    await save.last.click()
    await page.wait_for_timeout(1200)
    return {"success": True, "matchedOption": labels[index], "verified": True}


async def _product(page: Page, row_key: str, preview: bool) -> dict[str, Any]:
    if preview:
        return {"success": True, "preview": True}
    await page.locator(f'td[data-row-key="{row_key}"][data-column-name="_checked"] input').check()
    controls = page.locator('.pFunctions select, select').filter(has_text="진열상태변경")
    options = await controls.first.locator("option").evaluate_all("es=>es.map(e=>({t:e.textContent.trim(),v:e.value}))")
    hidden = next(item for item in options if "진열안함" in item["t"])
    await controls.first.select_option(hidden["v"])
    await page.get_by_text("수정저장", exact=True).click()
    await page.wait_for_timeout(1200)
    return {"success": True, "verified": True}


async def run(action: str, product_code: str, option_name: str | None = None, preview: bool = False) -> dict[str, Any]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=config.HEADLESS)
        page = await browser.new_page(viewport={"width": 1600, "height": 900})
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        try:
            await _login(page)
            row_key = await _search(page, product_code)
            result = await _option(page, row_key, option_name or "", preview) if action == "option-soldout" else await _product(page, row_key, preview)
            return {"site": SITE, "siteCode": SITE_CODE, "action": action, "productCode": product_code, **result}
        except Exception as exc:
            return failed(SITE, SITE_CODE, action, product_code, exc)
        finally:
            await browser.close()
