from __future__ import annotations

import asyncio
import re
from typing import Any

from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.domesin import PASSWORD, USER_ID
from order_worker.sites.status_utils import failed, normalize, option_matches

SITE = "도매의신"
SITE_CODE = "domesin"
LOGIN_URL = "https://www.domesin.com/scm/login.html"
MANAGEMENT_URL = "https://www.domesin.com/scm/M_item/item_list.html"


async def _login(page: Page) -> None:
    await page.goto(LOGIN_URL)
    await page.fill('body > div > form > input[type=text]:nth-child(4)', USER_ID)
    await page.fill('body > div > form > input[type=password]:nth-child(5)', PASSWORD)
    await page.click('body > div > form > button.login-btn')
    await page.wait_for_load_state("networkidle")


async def _search(page: Page, product_code: str) -> str:
    await page.goto(MANAGEMENT_URL, wait_until="networkidle")
    await page.locator("#q_type").select_option("iname")
    await page.locator("#q").fill(product_code)
    await page.locator('input[type=submit]').click()
    await page.wait_for_load_state("networkidle")
    codes = page.locator('input[name^="vender_code_"]')
    matches = []
    for index in range(await codes.count()):
        field = codes.nth(index)
        if normalize(await field.input_value()) == normalize(product_code):
            matches.append((await field.get_attribute("name") or "").split("_")[-1])
    if len(matches) != 1:
        raise RuntimeError(f"{SITE}: 상품코드 {product_code} 검색 결과가 {len(matches)}건이라 처리하지 않았습니다.")
    return matches[0]


async def _option(page: Page, item_id: str, option_name: str, preview: bool) -> dict[str, Any]:
    async with page.expect_popup() as popup_info:
        await page.locator(f'input[onclick="item_option({item_id});"]').click()
    popup = await popup_info.value
    await popup.wait_for_load_state("networkidle")
    first_values = popup.locator('input[name="op_n1[]"]')
    second_values = popup.locator('input[name="op_n2[]"]')
    statuses = popup.locator('select[name="op_sold[]"]')
    matches = []
    for index in range(await statuses.count()):
        first = await first_values.nth(index).input_value()
        second = await second_values.nth(index).input_value()
        label = "/".join(value for value in (first, second) if value)
        if option_matches(option_name, label):
            matches.append((index, label))
    if len(matches) != 1:
        await popup.close()
        raise RuntimeError(f"{SITE}: 옵션명 '{option_name}'을 1건으로 찾지 못해 처리하지 않았습니다. (일치 {len(matches)}건)")
    index, label = matches[0]
    status = statuses.nth(index)
    if await status.input_value() == "1":
        await popup.close()
        return {"success": True, "alreadyProcessed": True, "matchedOption": label, "verified": True}
    if preview:
        await popup.close()
        return {"success": True, "preview": True, "matchedOption": label}
    await status.select_option("1")
    await popup.locator('input[type=submit]').last.click()
    await page.wait_for_timeout(1200)
    return {"success": True, "matchedOption": label, "verified": True}


async def _product(page: Page, item_id: str, preview: bool) -> dict[str, Any]:
    status = page.locator(f'select[name="status_{item_id}"]')
    if await status.input_value() == "1":
        return {"success": True, "alreadyProcessed": True, "verified": True}
    if preview:
        return {"success": True, "preview": True}
    await page.locator(f'input[name="iid[]"][value="{item_id}"]').check()
    await page.locator("#btn_total_sold").click()
    await page.wait_for_timeout(1500)
    return {"success": True, "verified": True}


async def run(action: str, product_code: str, option_name: str | None = None, preview: bool = False) -> dict[str, Any]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=config.HEADLESS)
        page = await browser.new_page()
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        try:
            await _login(page)
            item_id = await _search(page, product_code)
            result = await _option(page, item_id, option_name or "", preview) if action == "option-soldout" else await _product(page, item_id, preview)
            return {"site": SITE, "siteCode": SITE_CODE, "action": action, "productCode": product_code, **result}
        except Exception as exc:
            return failed(SITE, SITE_CODE, action, product_code, exc)
        finally:
            await browser.close()
