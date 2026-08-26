from __future__ import annotations

import asyncio
import re
import unicodedata
from typing import Any

from playwright.async_api import Browser, Page, async_playwright

from order_worker import config
from order_worker.sites.ownerclan import ACCOUNTS
from order_worker.sites.status_utils import ProductNotFound, failed, product_not_found


MANAGEMENT_URL = "https://ownerclan.com/vender/product_myprd.php"
LOGIN_URL = "https://ownerclan.com/vender/login.php"


def _normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _target_tokens(option_name: str) -> list[str]:
    return [_normalize(value) for value in re.split(r"\s*(?:/|\||,)\s*", option_name) if value.strip()]


def option_values_match(option_name: str, remote_values: list[str]) -> bool:
    target = _target_tokens(option_name)
    remote = [_normalize(value) for value in remote_values if value.strip()]
    if not target:
        return False
    if len(target) == 1:
        return target[0] in remote
    return target == remote


async def _select_model_search(page: Page) -> None:
    search_type = page.locator('select[name="s_check"]:visible').first
    await search_type.wait_for(state="visible", timeout=10000)
    await search_type.select_option("model")


async def _accept_dialog(dialog) -> None:
    await dialog.accept()


async def _login(page: Page, account) -> None:
    _, user_id, password, label = account
    print(f"PROGRESS: [{label}] 로그인 중...")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await page.fill('input[name="id"]', user_id)
    await page.fill('input[name="passwd"]', password)
    await page.click('input[type="submit"]')
    await page.wait_for_load_state("networkidle")


async def _search_product(page: Page, product_code: str, account):
    for attempt in range(2):
        await page.goto(MANAGEMENT_URL, wait_until="networkidle")
        search_input = page.locator('input[name="search"]:visible').first
        if await search_input.count() == 1:
            break
        if attempt == 0:
            print("PROGRESS: [오너클랜] 로그인 세션 재확인...")
            await _login(page, account)
    else:
        raise RuntimeError(f"오너클랜 상품관리 화면에 접근하지 못했습니다: {page.url}")

    # 통합검색은 상품명 등에 같은 코드가 포함된 여러 상품을 반환할 수 있다.
    # 오너클랜의 모델명에는 인트라넷 G/F 코드가 정확히 저장되어 있으므로
    # 두 계정 모두 모델명으로 범위를 제한한 뒤 검색한다.
    await _select_model_search(page)
    await search_input.fill(product_code)
    await page.locator('button[onclick*="SearchPrd"]:visible').first.click()
    await page.wait_for_load_state("networkidle")

    edit_links = page.locator('a[href*="GoPrdinfo"]')
    count = await edit_links.count()
    if count == 0:
        raise ProductNotFound(product_code)
    if count != 1:
        raise RuntimeError(f"오너클랜 상품 검색 결과가 1건이 아닙니다: {product_code} ({count}건)")
    row = edit_links.first.locator("xpath=ancestor::tr[1]")
    row_text = await row.inner_text()
    if _normalize(product_code) not in _normalize(row_text):
        raise RuntimeError(f"오너클랜 검색 결과에서 상품코드를 확인하지 못했습니다: {product_code}")
    return row, edit_links.first


async def _open_editor(page: Page, edit_link) -> Page:
    async with page.expect_popup(timeout=15000) as popup_info:
        await edit_link.click()
    editor = await popup_info.value
    await editor.wait_for_load_state("networkidle")
    editor.on("dialog", lambda dialog: asyncio.create_task(_accept_dialog(dialog)))
    return editor


async def _open_option_editor(editor: Page) -> Page:
    async with editor.expect_popup(timeout=15000) as popup_info:
        await editor.locator("#btn_option").click()
    option_page = await popup_info.value
    await option_page.wait_for_load_state("networkidle")
    option_page.on("dialog", lambda dialog: asyncio.create_task(_accept_dialog(dialog)))
    return option_page


async def _find_option_row(option_page: Page, option_name: str) -> tuple[int, list[str], str]:
    first_values = option_page.locator(".opValName1")
    second_values = option_page.locator(".opValName2")
    statuses = option_page.locator("select.opStatus")
    matches: list[tuple[int, list[str], str]] = []

    for index in range(await statuses.count()):
        values: list[str] = []
        if index < await first_values.count():
            values.append(await first_values.nth(index).input_value())
        if index < await second_values.count():
            values.append(await second_values.nth(index).input_value())
        if option_values_match(option_name, values):
            matches.append((index, values, await statuses.nth(index).input_value()))

    if len(matches) != 1:
        found = ["/".join(item[1]) for item in matches]
        raise RuntimeError(f"오너클랜 옵션을 한 건으로 특정하지 못했습니다: {option_name} (일치: {found})")
    return matches[0]


async def _verify_option_status(page: Page, product_code: str, option_name: str, wanted: str, account) -> list[str]:
    _, edit_link = await _search_product(page, product_code, account)
    editor = await _open_editor(page, edit_link)
    try:
        option_page = await _open_option_editor(editor)
        try:
            _, values, status = await _find_option_row(option_page, option_name)
            if status != wanted:
                raise RuntimeError(f"오너클랜 옵션 상태 저장을 확인하지 못했습니다: {'/'.join(values)}")
            return values
        finally:
            if not option_page.is_closed():
                await option_page.close()
    finally:
        if not editor.is_closed():
            await editor.close()


async def option_status(page: Page, product_code: str, option_name: str, account, preview: bool = False, restock: bool = False) -> dict[str, Any]:
    _, edit_link = await _search_product(page, product_code, account)
    editor = await _open_editor(page, edit_link)
    try:
        option_page = await _open_option_editor(editor)
        index, values, current_status = await _find_option_row(option_page, option_name)
        label = "/".join(values)
        wanted = "SELL" if restock else "SOLDOUT"
        if current_status == wanted:
            return {"success": True, "alreadyProcessed": True, "matchedOption": label}
        if preview:
            return {"success": True, "preview": True, "matchedOption": label, "currentStatus": current_status}

        print(f"PROGRESS: [오너클랜] {product_code} / {label} 옵션 상태 변경...")
        await option_page.locator("select.opStatus").nth(index).select_option(wanted)
        await option_page.locator('button[onclick*="setupOption"]').click()
        await editor.wait_for_function(
            f"() => {{ try {{ const data = JSON.parse(document.querySelector('#optionsData').value); return data.optionList.some(v => v.status === '{wanted}' || v.sale_status === '{wanted}' || v.opStatus === '{wanted}'); }} catch (_) {{ return true; }} }}",
            timeout=10000,
        )

        print(f"PROGRESS: [오너클랜] {product_code} 상품 수정 저장...")
        await editor.locator('a[href*="formSubmit(\'update\')"]').click()
        await page.wait_for_timeout(2500)
    finally:
        if not editor.is_closed():
            await editor.close()

    verified_values = await _verify_option_status(page, product_code, option_name, wanted, account)
    return {"success": True, "matchedOption": "/".join(verified_values), "verified": True}


async def product_status(page: Page, product_code: str, account, preview: bool = False, restock: bool = False) -> dict[str, Any]:
    row, _ = await _search_product(page, product_code, account)
    row_text = await row.inner_text()
    is_soldout = "품절" in row_text
    if is_soldout != restock:
        return {"success": True, "alreadyProcessed": True, "verified": True}
    if preview:
        return {"success": True, "preview": True, "currentStatus": "판매중"}

    checkbox = row.locator('input[name="chkprcode"]')
    if await checkbox.count() != 1:
        raise RuntimeError(f"오너클랜 상품 선택 체크박스를 찾지 못했습니다: {product_code}")
    await checkbox.check()
    if restock:
        status_selects = page.locator("select:visible")
        status_select = None
        for index in range(await status_selects.count()):
            candidate = status_selects.nth(index)
            labels = await candidate.locator("option").all_text_contents()
            normalized = {label.strip() for label in labels}
            if {"판매중", "품절"}.issubset(normalized):
                status_select = candidate
        if status_select is not None:
            await status_select.select_option(label="판매중")
            await page.wait_for_timeout(2500)
        else:
            menu_button = page.locator("button:visible").filter(has_text="판매 상태 변경").first
            if await menu_button.count() != 1:
                raise RuntimeError(f"오너클랜 상품 재입고 판매상태 변경 메뉴를 찾지 못했습니다: {product_code}")
            await menu_button.click()
            sale_item = page.get_by_text("판매중", exact=True).last
            await sale_item.wait_for(state="visible", timeout=5000)
            await sale_item.click()
            await page.wait_for_timeout(2500)
    else:
        button = page.locator('[onclick*="temp_soldout"]:visible').first
        if await button.count() != 1:
            raise RuntimeError(f"오너클랜 상품 품절 버튼을 찾지 못했습니다: {product_code}")
        await button.click()
        await page.wait_for_timeout(2500)

    verified_row, _ = await _search_product(page, product_code, account)
    if ("품절" in await verified_row.inner_text()) == restock:
        raise RuntimeError(f"오너클랜 상품 상태 저장을 확인하지 못했습니다: {product_code}")
    return {"success": True, "verified": True}


async def run(action: str, product_code: str, option_name: str | None = None, preview: bool = False, account_code: str = "ownerclan") -> dict[str, Any]:
    account = next((item for item in ACCOUNTS if item[0] == account_code), None)
    if account is None:
        raise ValueError(f"지원하지 않는 오너클랜 계정입니다: {account_code}")
    site_code, _, _, site = account
    async with async_playwright() as playwright:
        browser: Browser = await playwright.chromium.launch(headless=config.HEADLESS)
        context = await browser.new_context()
        page = await context.new_page()
        page.on("dialog", lambda dialog: asyncio.create_task(_accept_dialog(dialog)))
        try:
            await _login(page, account)
            if action.startswith("option-"):
                if not option_name:
                    raise ValueError("옵션 품절에는 옵션명이 필요합니다.")
                result = await option_status(page, product_code, option_name, account, preview=preview, restock=action.endswith("restock"))
            elif action.startswith("product-"):
                result = await product_status(page, product_code, account, preview=preview, restock=action.endswith("restock"))
            else:
                raise ValueError(f"지원하지 않는 품절 작업입니다: {action}")
            return {"site": site, "siteCode": site_code, "action": action, "productCode": product_code, **result}
        except ProductNotFound:
            return product_not_found(site, site_code, action, product_code)
        except Exception as exc:
            return failed(site, site_code, action, product_code, exc)
        finally:
            await browser.close()
