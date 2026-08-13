from __future__ import annotations

import asyncio
from typing import Any

from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.specialoffer import PASSWORD, USER_ID
from order_worker.sites.status_utils import failed, normalize, option_matches

SITE = "스페셜오퍼"
SITE_CODE = "specialoffer"
LOGIN_URL = "https://specialoffer.kr/bbs/login.php"
MANAGEMENT_URL = "https://specialoffer.kr/mypage/page.php?code=seller_goods_change"


async def _login(page: Page) -> None:
    await page.goto(LOGIN_URL)
    await page.fill("#login_id", USER_ID)
    await page.fill("#login_pw", PASSWORD)
    await page.click("#login_fld > dl > dd:nth-child(5) > button")
    await page.wait_for_url(lambda url: "/bbs/login.php" not in url, timeout=30000)


async def _search(page: Page, product_code: str):
    await page.goto(MANAGEMENT_URL, wait_until="domcontentloaded")
    await page.locator('input[type=button][onclick*="search_date"]').last.click()
    await page.locator('select[name="sfl"]').select_option("gname")
    await page.locator('input[name="stx"]').fill(product_code)
    await page.locator('input[type=submit]').click()
    await page.wait_for_load_state("domcontentloaded")
    rows = page.locator("tbody tr").filter(has_text=product_code)
    matches = []
    for index in range(await rows.count()):
        row = rows.nth(index)
        if normalize(product_code) in normalize(await row.inner_text()):
            matches.append(row)
    if len(matches) != 1:
        raise RuntimeError(f"{SITE}: 상품코드 {product_code} 검색 결과가 {len(matches)}건이라 처리하지 않았습니다.")
    return matches[0]


async def _option(page: Page, row, option_name: str, preview: bool) -> dict[str, Any]:
    detail = row.locator('a[href*="seller_goods_form"]')
    if await detail.count() != 1:
        raise RuntimeError(f"{SITE}: 상품 수정 링크를 찾지 못했습니다.")
    async with page.expect_popup() as popup_info:
        await detail.click()
    editor = await popup_info.value
    await editor.wait_for_load_state("domcontentloaded")
    await editor.wait_for_function(
        "() => window.oEditors && window.oEditors.getById && window.oEditors.getById.memo "
        "&& typeof window.oEditors.getById.memo.getIR === 'function'",
        timeout=30000,
    )
    option_rows = editor.locator("#sit_option_frm tbody tr")
    matches = []
    for index in range(await option_rows.count()):
        candidate = option_rows.nth(index)
        text = await candidate.inner_text()
        label = text.splitlines()[0].strip().replace(" > ", "/") if text.strip() else ""
        if option_matches(option_name, label):
            matches.append((candidate, label))
    if len(matches) != 1:
        raise RuntimeError(f"{SITE}: 옵션명 '{option_name}'을 1건으로 찾지 못해 처리하지 않았습니다. (일치 {len(matches)}건)")
    target, label = matches[0]
    stock = target.locator('input[name="opt_stock_qty[]"]')
    use = target.locator('select[name="opt_use[]"]')
    if (await stock.input_value()).replace(",", "") == "0" and await use.input_value() == "0":
        return {"success": True, "alreadyProcessed": True, "matchedOption": label, "verified": True}
    if preview:
        return {"success": True, "preview": True, "matchedOption": label}
    if await stock.count():
        await stock.fill("0")
    await use.select_option("0")
    option_checkbox = target.locator('input[name="opt_chk[]"]')
    if await option_checkbox.count():
        await option_checkbox.check()
    await editor.locator("#modify_status").select_option("9")
    await editor.locator('textarea[name="modify_msg_after"]').fill(".")
    await editor.evaluate("GoodsForm.save()")
    confirm = editor.locator('.swal2-confirm, .notiflix-confirm-button-ok, .nx-confirm-button-ok, button').filter(has_text="확인")
    if await confirm.count():
        await confirm.last.click()
    await editor.wait_for_url(lambda url: "seller_goods_form" not in url, timeout=30000)
    return {
        "success": True,
        "matchedOption": label,
        "verified": True,
        "message": "옵션 품절 수정요청 제출 완료",
    }


async def _product(page: Page, row, preview: bool) -> dict[str, Any]:
    if preview:
        return {"success": True, "preview": True}
    await row.locator('input[type=checkbox]').check()
    await page.locator('button[onclick*="GoodsChange.pop"][onclick*="\'1\'"]').first.click()
    modal = page.locator('.modal:visible, [class*=popup]:visible').last
    textarea = modal.locator("textarea").last
    if await textarea.count():
        await textarea.fill(".")
    await modal.locator('input[type=submit], button[type=submit]').last.click()
    return {"success": True, "verified": True}


async def run(action: str, product_code: str, option_name: str | None = None, preview: bool = False) -> dict[str, Any]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=config.HEADLESS)
        page = await browser.new_page()
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        try:
            await _login(page)
            row = await _search(page, product_code)
            result = await _option(page, row, option_name or "", preview) if action == "option-soldout" else await _product(page, row, preview)
            return {"site": SITE, "siteCode": SITE_CODE, "action": action, "productCode": product_code, **result}
        except Exception as exc:
            return failed(SITE, SITE_CODE, action, product_code, exc)
        finally:
            await browser.close()
