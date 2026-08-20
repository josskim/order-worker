from __future__ import annotations

import asyncio
import re
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


async def _accept_dialog(dialog) -> None:
    await dialog.accept()


async def _click_visible_confirm(page: Page, timeout: int = 10000) -> bool:
    confirm = page.locator(
        '.swal2-confirm:visible, '
        '.notiflix-confirm:visible button:has-text("확인"), '
        '.nx-confirm:visible button:has-text("확인"), '
        '[role="dialog"]:visible button:has-text("확인")'
    ).last
    try:
        await confirm.wait_for(state="visible", timeout=timeout)
        await confirm.click(force=True)
        return True
    except Exception:
        return False


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


async def _option(page: Page, row, product_code: str, option_name: str, preview: bool, restock: bool = False) -> dict[str, Any]:
    detail = row.locator('a[href*="seller_goods_form"]')
    if await detail.count() != 1:
        raise RuntimeError(f"{SITE}: 상품 수정 링크를 찾지 못했습니다.")
    async with page.expect_popup() as popup_info:
        await detail.click()
    editor = await popup_info.value
    editor.on("dialog", lambda dialog: asyncio.create_task(_accept_dialog(dialog)))
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
    wanted_qty, wanted_use = ("9999", "1") if restock else ("0", "0")
    if (await stock.input_value()).replace(",", "") == wanted_qty and await use.input_value() == wanted_use:
        return {"success": True, "alreadyProcessed": True, "matchedOption": label, "verified": True}
    if preview:
        return {"success": True, "preview": True, "matchedOption": label}
    if await stock.count():
        await stock.fill(wanted_qty)
    await use.select_option(wanted_use)
    await editor.locator("#modify_status").select_option("9")
    await editor.locator('textarea[name="modify_msg_after"]').fill(".")
    save_button = editor.get_by_role("button", name="저장", exact=True)
    if await save_button.count() != 1:
        raise RuntimeError(f"{SITE}: 상품 수정 저장 버튼을 찾지 못했습니다.")
    await save_button.click()
    async with editor.expect_response(
        lambda response: "seller_goods_form_update.php" in response.url,
        timeout=30000,
    ) as response_info:
        await _click_visible_confirm(editor)
    update_response = await response_info.value
    if update_response.status >= 400:
        raise RuntimeError(f"{SITE}: 옵션 저장 요청이 HTTP {update_response.status}로 실패했습니다.")
    if not editor.is_closed():
        await editor.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(1500)
    verified_row = await _search(page, product_code)
    verify_detail = verified_row.locator('a[href*="seller_goods_form"]')
    async with page.expect_popup() as verify_popup:
        await verify_detail.click()
    verify_editor = await verify_popup.value
    try:
        await verify_editor.wait_for_load_state("domcontentloaded")
        verify_rows = verify_editor.locator("#sit_option_frm tbody tr")
        verified = False
        for index in range(await verify_rows.count()):
            candidate = verify_rows.nth(index)
            candidate_label = (await candidate.inner_text()).splitlines()[0].strip().replace(" > ", "/")
            if option_matches(option_name, candidate_label):
                qty = (await candidate.locator('input[name="opt_stock_qty[]"]').input_value()).replace(",", "")
                enabled = await candidate.locator('select[name="opt_use[]"]').input_value()
                verified = qty == wanted_qty and enabled == wanted_use
                break
        if not verified:
            raise RuntimeError(f"{SITE}: 저장 후 옵션 상태가 즉시 반영되지 않았습니다: {label}")
    finally:
        if not verify_editor.is_closed():
            await verify_editor.close()
    return {
        "success": True,
        "matchedOption": label,
        "verified": True,
        "message": f"옵션 {'재입고' if restock else '품절'} 즉시 반영 완료",
    }


async def _product(page: Page, row, product_code: str, preview: bool, restock: bool = False) -> dict[str, Any]:
    if preview:
        return {"success": True, "preview": True}
    await row.locator('input[type=checkbox]').check()
    button_label = "선택 상품 일괄 재입고" if restock else "선택 상품 일괄 품절"
    action_button = page.locator('button[name="act_button"]:visible').filter(has_text="일괄 재입고" if restock else "일괄 품절")
    if await action_button.count() == 0:
        opposite = "선택 상품 일괄 품절" if restock else "선택 상품 일괄 재입고"
        if await page.locator('button[name="act_button"]:visible').filter(has_text="일괄 품절" if restock else "일괄 재입고").count():
            return {"success": True, "alreadyProcessed": True, "verified": True}
        raise RuntimeError(f"{SITE}: {button_label} 버튼을 찾지 못했습니다.")
    async with page.expect_popup() as popup_info:
        await action_button.first.click(no_wait_after=True)
    popup = await popup_info.value
    popup.on("dialog", lambda dialog: asyncio.create_task(_accept_dialog(dialog)))
    await popup.wait_for_load_state("domcontentloaded")
    status = popup.locator('select[name="status"]')
    options = await status.locator("option").evaluate_all("es=>es.map(e=>({t:e.textContent.trim(),v:e.value}))")
    wanted_text = "재입고" if restock else "품절"
    wanted = next((item for item in options if item["t"] == wanted_text), None)
    if wanted:
        await status.select_option(wanted["v"])
    textarea = popup.locator('textarea[name="msg[all][after]"]')
    if await textarea.count():
        await textarea.fill(".")
    submit = popup.locator('input[type=submit][value="등록"]')
    if await submit.count() == 0:
        raise RuntimeError(f"{SITE}: 상품 상태 변경 등록 버튼을 찾지 못했습니다.")
    await submit.click(no_wait_after=True)
    await _click_visible_confirm(popup, timeout=5000)
    await page.wait_for_timeout(1800)
    verified_row = await _search(page, product_code)
    is_soldout = "품절" in await verified_row.inner_text()
    if is_soldout == restock:
        raise RuntimeError(f"{SITE}: 저장 후 상품 {'재입고' if restock else '품절'} 상태가 반영되지 않았습니다.")
    return {
        "success": True,
        "verified": True,
        "message": f"상품 {'재입고' if restock else '품절'} 처리 완료",
    }


async def run(action: str, product_code: str, option_name: str | None = None, preview: bool = False) -> dict[str, Any]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=config.HEADLESS)
        page = await browser.new_page()
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        try:
            await _login(page)
            row = await _search(page, product_code)
            restock = action.endswith("restock")
            result = await _option(page, row, product_code, option_name or "", preview, restock) if action.startswith("option-") else await _product(page, row, product_code, preview, restock)
            return {"site": SITE, "siteCode": SITE_CODE, "action": action, "productCode": product_code, **result}
        except Exception as exc:
            return failed(SITE, SITE_CODE, action, product_code, exc)
        finally:
            await browser.close()
