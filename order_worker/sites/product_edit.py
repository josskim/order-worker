from __future__ import annotations

import asyncio
from typing import Any, Callable
from urllib.parse import urljoin

from playwright.async_api import Browser, async_playwright

from order_worker import config
from order_worker.sites import domeggook_status, domesin_status, namdo_status, ownerclan_status, onchannel_status, specialoffer_status
from order_worker.sites.domeggook import ACCOUNTS as DOMEGGOOK_ACCOUNTS
from order_worker.sites.onchannel import ACCOUNTS as ONCHANNEL_ACCOUNTS
from order_worker.sites.ownerclan import ACCOUNTS as OWNERCLAN_ACCOUNTS
from order_worker.sites.status_utils import ProductNotFound, failed


LABELS = {
    "ownerclan": "오너클랜",
    "Fownerclan": "F오너클랜",
    "onchannel": "온채널",
    "Fonch3": "F온채널",
    "domeggook": "도매꾹",
    "Fdomeggook": "F도매꾹",
    "specialoffer": "스페셜오퍼",
    "domesin": "도매의신",
    "namdo": "남도마켓",
}

PRICE_KEYS = {
    "onchannel": "onch3",
    "specialoffer": "special",
    "domesin": "domegod",
}


def _price(changes: dict[str, Any], site_code: str) -> int | None:
    prices = changes.get("prices") if isinstance(changes.get("prices"), dict) else {}
    key = PRICE_KEYS.get(site_code, site_code)
    raw = prices.get(key)
    return int(raw) if raw is not None else None


def _title(changes: dict[str, Any], site_code: str) -> str:
    key = PRICE_KEYS.get(site_code, site_code)
    title_sites = {str(value) for value in changes.get("titleSites", [])}
    return str(changes.get("title") or "").strip() if key in title_sites else ""


def _message(applied: list[str], preview: bool) -> dict[str, Any]:
    joined = ", ".join(applied)
    return {
        "success": True,
        "preview": preview,
        "verified": not preview,
        "message": f"{'수정 대상 확인' if preview else '상품 수정 완료'}: {joined}",
    }


async def _ownerclan(browser: Browser, site_code: str, product_code: str, changes: dict[str, Any], preview: bool) -> dict[str, Any]:
    account = next((item for item in OWNERCLAN_ACCOUNTS if item[0] == site_code), None)
    if account is None:
        raise RuntimeError(f"오너클랜 계정 설정이 없습니다: {site_code}")
    page = await browser.new_page()
    editor = None
    try:
        await ownerclan_status._login(page, account)
        _, edit_link = await ownerclan_status._search_product(page, product_code, account)
        editor = await ownerclan_status._open_editor(page, edit_link)
        applied: list[str] = []
        title = _title(changes, site_code)
        price = _price(changes, site_code)
        if title:
            await editor.locator('input[name="productname"]').fill(title)
            applied.append("상품명")
        if price is not None:
            await editor.locator("#sellprice").fill(str(price))
            applied.append("판매금액")
        if preview:
            return _message(applied, True)
        await editor.locator('a[href*="formSubmit(\'update\')"]').click()
        await page.wait_for_timeout(3500)
        return _message(applied, False)
    finally:
        if editor is not None and not editor.is_closed():
            await editor.close()
        await page.close()


async def _onchannel(browser: Browser, site_code: str, product_code: str, changes: dict[str, Any], preview: bool) -> dict[str, Any]:
    account_code = "onch3" if site_code == "onchannel" else site_code
    account = next((item for item in ONCHANNEL_ACCOUNTS if item[0] == account_code), None)
    if account is None:
        raise RuntimeError(f"온채널 계정 설정이 없습니다: {site_code}")
    page = await browser.new_page()
    editor = None
    try:
        await onchannel_status._login(page, account)
        row = await onchannel_status._search(page, product_code)
        async with page.expect_popup(timeout=15000) as popup_info:
            await row.locator(".btn-modi-product").click()
        editor = await popup_info.value
        await editor.wait_for_load_state("domcontentloaded")
        applied: list[str] = []
        title = _title(changes, site_code)
        price = _price(changes, site_code)
        if title:
            await editor.locator('input[name="product_nm"]').fill(title)
            applied.append("상품명")
        if price is not None:
            await editor.get_by_role("button", name="가격/옵션 정보 입력", exact=True).click(no_wait_after=True)
            await editor.wait_for_timeout(300)
            price_fields = editor.locator('input[name^="options["][name$="[onch_price]"]')
            if await price_fields.count() == 0:
                raise RuntimeError("온채널 상품 수정 화면에서 기존 옵션 공급가 입력란을 찾지 못했습니다.")
            for index in range(await price_fields.count()):
                await price_fields.nth(index).fill(str(price))
            applied.append("공급가")
        if preview:
            return _message(applied, True)
        # The edit popup exposes the action visually as "승인 요청", but its
        # accessibility name is not stable. The site-owned class is the
        # reliable selector on the live form.
        save = editor.locator("button.btn-approve-request:visible").last
        if await save.count() == 0:
            # Title-only edits stay on the basic-information tab, where the
            # final action is rendered but hidden. Move to the second step.
            await editor.get_by_role("button", name="가격/옵션 정보 입력", exact=True).click(no_wait_after=True)
            await editor.wait_for_timeout(300)
            save = editor.locator("button.btn-approve-request:visible").last
        if await save.count() == 0:
            raise RuntimeError("온채널 상품 수정 저장 버튼을 찾지 못했습니다.")
        await save.click()
        await editor.wait_for_timeout(1800)
        return _message(applied, False)
    finally:
        if editor is not None and not editor.is_closed():
            await editor.close()
        await page.close()


async def _domeggook(browser: Browser, site_code: str, product_code: str, changes: dict[str, Any], preview: bool) -> dict[str, Any]:
    account = next((item for item in DOMEGGOOK_ACCOUNTS if item[0] == site_code), None)
    if account is None:
        raise RuntimeError(f"도매꾹 계정 설정이 없습니다: {site_code}")
    page = await browser.new_page(viewport={"width": 1800, "height": 1200})
    page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
    try:
        await domeggook_status._login(page, account)
        row_key = await domeggook_status._search(page, product_code)
        item_no = (await page.locator(f'td[data-row-key="{row_key}"][data-column-name="no"]').inner_text()).strip()
        await page.goto(f"https://www.domeggook.com/sc/item/editFrm/{item_no}", wait_until="domcontentloaded")
        applied: list[str] = []
        title = _title(changes, site_code)
        price = _price(changes, site_code)
        if title:
            await page.locator('input[name="itemTitle"]').fill(title)
            applied.append("상품명")
        if price is not None:
            await page.evaluate(
                """price => {
                  module.itemAmtSectionTbl.updateData({idx:0,key:'amt',val:String(price)});
                  module.itemSupplyAmtSectionTbl.updateData({idx:0,key:'amt',val:String(price)});
                }""",
                price,
            )
            applied.append("판매금액")
        if preview:
            return _message(applied, True)
        blocking_notice = page.locator("#lDialogSellReg:visible .pDialogBtnClose:visible").last
        if await blocking_notice.count():
            await blocking_notice.click()
            await page.wait_for_timeout(250)
        # Domeggook replaced the old #lBtnShowSubmitHelp control with the
        # common navy submit button on the edit form.
        submit = page.locator("button.lBtnSubmit.lBtnNavy:visible").last
        if await submit.count() == 0:
            raise RuntimeError("도매꾹 상품 수정 저장 버튼을 찾지 못했습니다.")
        await submit.click()
        await page.wait_for_timeout(600)
        confirm = page.locator(".pDialog:visible .pDialogBtnHighlighted:visible").last
        if await confirm.count():
            await confirm.click()
        await page.wait_for_timeout(1800)
        return _message(applied, False)
    finally:
        await page.close()


async def _specialoffer(browser: Browser, site_code: str, product_code: str, changes: dict[str, Any], preview: bool) -> dict[str, Any]:
    page = await browser.new_page()
    page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
    try:
        await specialoffer_status._login(page)
        row = await specialoffer_status._search(page, product_code)
        href = await row.locator('a[href*="seller_goods_form"]').get_attribute("href")
        if not href:
            raise RuntimeError("스페셜오퍼 상품 수정 주소를 찾지 못했습니다.")
        await page.goto(urljoin(page.url, href), wait_until="domcontentloaded")
        applied: list[str] = []
        title = _title(changes, site_code)
        price = _price(changes, site_code)
        if title:
            await page.locator('input[name="gname"]').fill(title)
            applied.append("상품명")
        if price is not None:
            await page.locator("#supply_price").fill(str(price))
            applied.append("공급가격")
        if preview:
            return _message(applied, True)
        if await page.locator("#modify_status").count():
            await page.locator("#modify_status").select_option("9")
        if await page.locator('textarea[name="modify_msg_after"]').count():
            await page.locator('textarea[name="modify_msg_after"]').fill(".")
        save = page.get_by_role("button", name="저장", exact=True)
        if await save.count() == 0:
            raise RuntimeError("스페셜오퍼 상품 수정 저장 버튼을 찾지 못했습니다.")
        await save.click()
        await specialoffer_status._click_visible_confirm(page)
        await page.wait_for_timeout(1800)
        return _message(applied, False)
    finally:
        await page.close()


async def _domesin(browser: Browser, site_code: str, product_code: str, changes: dict[str, Any], preview: bool) -> dict[str, Any]:
    page = await browser.new_page()
    page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
    try:
        await domesin_status._login(page)
        item_id = await domesin_status._search(page, product_code)
        applied: list[str] = []
        title = _title(changes, site_code).replace("_", " ")
        price = _price(changes, site_code)
        if title:
            await page.locator(f'input[name="iname_{item_id}"]').fill(title)
            applied.append("상품명")
        if price is not None:
            await page.locator(f'input[name="cost_{item_id}"]').fill(str(price))
            applied.append("판매가")
        if preview:
            return _message(applied, True)
        await page.locator(f'input[name="iid[]"][value="{item_id}"]').check()
        save = page.locator('input[type="button"], input[type="submit"], button').filter(has_text="선택수정").first
        if await save.count() == 0:
            save = page.locator('input[value*="수정저장"], input[value*="선택수정"], button:has-text("수정저장")').first
        if await save.count() == 0:
            raise RuntimeError("도매의신 선택 상품 수정 저장 버튼을 찾지 못했습니다.")
        await save.click()
        await page.wait_for_timeout(1600)
        return _message(applied, False)
    finally:
        await page.close()


async def _namdo(browser: Browser, site_code: str, product_code: str, changes: dict[str, Any], preview: bool) -> dict[str, Any]:
    from order_worker.sites.namdo_registration import _login

    page = await browser.new_page(viewport={"width": 1800, "height": 1200})
    try:
        await _login(page)
        await namdo_status._open_edit(page, product_code)
        applied: list[str] = []
        title = _title(changes, site_code)
        price = _price(changes, site_code)
        if title:
            await page.get_by_placeholder("상품명 입력 해주세요", exact=True).fill(title)
            applied.append("상품명")
        if price is not None:
            await page.get_by_placeholder("판매 가격을 입력해주세요.", exact=True).fill(str(price))
            applied.append("판매가격")
        if preview:
            return _message(applied, True)
        save = page.get_by_role("button", name="수정하기", exact=True)
        if await save.count() != 1:
            raise RuntimeError("남도마켓 상품 수정 저장 버튼을 찾지 못했습니다.")
        await save.click()
        await page.wait_for_timeout(1800)
        return _message(applied, False)
    finally:
        await page.close()


RUNNERS: dict[str, Callable[..., Any]] = {
    "ownerclan": _ownerclan,
    "Fownerclan": _ownerclan,
    "onchannel": _onchannel,
    "Fonch3": _onchannel,
    "domeggook": _domeggook,
    "Fdomeggook": _domeggook,
    "specialoffer": _specialoffer,
    "domesin": _domesin,
    "namdo": _namdo,
}


async def run_sites(
    request: dict[str, Any],
    *,
    preview: bool = False,
    on_progress: Callable[[str | None, list[dict[str, Any]]], None] | None = None,
) -> list[dict[str, Any]]:
    sites = [str(value) for value in request.get("workerSites", [])]
    changes = request.get("changes") if isinstance(request.get("changes"), dict) else {}
    site_codes = request.get("siteProductCodes") if isinstance(request.get("siteProductCodes"), dict) else {}
    results = list(request.get("preResults") or [])
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=config.HEADLESS)
        try:
            for site_code in sites:
                if on_progress:
                    on_progress(site_code, results.copy())
                product_code = str(site_codes.get(site_code) or request.get("productCode") or "").strip()
                runner = RUNNERS.get(site_code)
                if runner is None:
                    results.append(failed(LABELS.get(site_code, site_code), site_code, "product-edit", product_code, "상품 수정 자동화가 연결되지 않았습니다."))
                    continue
                try:
                    result = await asyncio.wait_for(runner(browser, site_code, product_code, changes, preview), timeout=240)
                    results.append({"site": LABELS.get(site_code, site_code), "siteCode": site_code, "productCode": product_code, **result})
                except ProductNotFound:
                    results.append(failed(LABELS.get(site_code, site_code), site_code, "product-edit", product_code, "상품을 찾지 못했습니다."))
                except Exception as exc:
                    results.append(failed(LABELS.get(site_code, site_code), site_code, "product-edit", product_code, exc))
                if on_progress:
                    on_progress(None, results.copy())
        finally:
            await browser.close()
    return results
