from __future__ import annotations

import asyncio
import re
from typing import Any, Callable
from urllib.parse import urljoin

from playwright.async_api import Browser, async_playwright

from order_worker import config
from order_worker.sites import domeggook_status, domesin_status, laf, namdo_status, ownerclan_status, onchannel_status, specialoffer_status
from order_worker.sites.domeggook import ACCOUNTS as DOMEGGOOK_ACCOUNTS
from order_worker.sites.onchannel import ACCOUNTS as ONCHANNEL_ACCOUNTS
from order_worker.sites.ownerclan import ACCOUNTS as OWNERCLAN_ACCOUNTS
from order_worker.sites.status_utils import ProductNotFound, failed, normalize, option_matches, product_not_found


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
    "cafe_laf": "라프",
}

SITE_KEYS = {
    "onchannel": "onch3",
    "specialoffer": "special",
    "domesin": "domegod",
}


def _price(changes: dict[str, Any], site_code: str) -> int | None:
    prices = changes.get("prices") if isinstance(changes.get("prices"), dict) else {}
    key = SITE_KEYS.get(site_code, site_code)
    raw = prices.get(key)
    return int(raw) if raw is not None else None


def _title(changes: dict[str, Any], site_code: str) -> str:
    key = SITE_KEYS.get(site_code, site_code)
    title_sites = {str(value) for value in changes.get("titleSites", [])}
    return str(changes.get("title") or "").strip() if key in title_sites else ""


def _option_labels(changes: dict[str, Any], site_code: str) -> list[str]:
    key = SITE_KEYS.get(site_code, site_code)
    option_sites = {str(value) for value in changes.get("optionSites", [])}
    if key not in option_sites:
        return []
    labels: list[str] = []
    seen: set[str] = set()
    for raw in changes.get("addOptions", []):
        label = str(raw).strip()
        if not label:
            continue
        normalized = normalize(label)
        if normalized not in seen:
            seen.add(normalized)
            labels.append(label)
    return labels


def _option_pairs(changes: dict[str, Any], site_code: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for label in _option_labels(changes, site_code):
        parts = [part.strip() for part in label.split("/")]
        if len(parts) != 2 or not all(parts):
            raise RuntimeError(f"외부 판매사이트 옵션은 '색상 / 사이즈' 형식이어야 합니다: {label}")
        pair = (parts[0], parts[1])
        if not any(option_matches(label, "/".join(existing)) for existing in pairs):
            pairs.append(pair)
    return pairs


def _pair_exists(pairs: list[tuple[str, str]], wanted: tuple[str, str]) -> bool:
    label = "/".join(wanted)
    return any(option_matches(label, "/".join(pair)) for pair in pairs)


def _is_product_not_found_error(error: Exception) -> bool:
    return isinstance(error, ProductNotFound) or bool(
        re.search(r"상품(?:코드)?.*(?:검색 결과가 0건|찾지 못했습니다)", str(error))
    )


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
    option_page = None
    try:
        await ownerclan_status._login(page, account)
        _, edit_link = await ownerclan_status._search_product(page, product_code, account)
        editor = await ownerclan_status._open_editor(page, edit_link)
        applied: list[str] = []
        title = _title(changes, site_code)
        price = _price(changes, site_code)
        requested_options = _option_pairs(changes, site_code)
        if title:
            await editor.locator('input[name="productname"]').fill(title)
            applied.append("상품명")
        if price is not None:
            await editor.locator("#sellprice").fill(str(price))
            applied.append("판매금액")
        missing_options: list[tuple[str, str]] = []
        if requested_options:
            option_page = await ownerclan_status._open_option_editor(editor)
            first_values = option_page.locator(".opValName1")
            second_values = option_page.locator(".opValName2")
            existing = [
                (
                    await first_values.nth(index).input_value(),
                    await second_values.nth(index).input_value() if index < await second_values.count() else "",
                )
                for index in range(await first_values.count())
            ]
            missing_options = [pair for pair in requested_options if not _pair_exists(existing, pair)]
            applied.append(f"옵션 {'추가 ' + str(len(missing_options)) + '개' if missing_options else '이미 존재'}")
            if not preview:
                for color, size in missing_options:
                    before = await option_page.locator(".opValName1").count()
                    await option_page.locator("#btn-add-empty-row").click()
                    await option_page.wait_for_timeout(150)
                    if await option_page.locator(".opValName1").count() != before + 1:
                        raise RuntimeError("오너클랜 새 옵션 입력 행이 생성되지 않았습니다.")
                    await option_page.locator(".opValName1").nth(before).fill(color)
                    await option_page.locator(".opValName2").nth(before).fill(size)
                    for selector in ('input[name="optionsellprice"]', 'input[name="optionbuyprice"]'):
                        field = option_page.locator(selector).nth(before)
                        if await field.count() and await field.is_editable() and not (await field.input_value()).strip():
                            await field.fill("0")
                if missing_options:
                    await option_page.locator('button[onclick*="setupOption"]').click()
                    await editor.wait_for_timeout(500)
                    if not await editor.locator("#optionsData").input_value():
                        raise RuntimeError("오너클랜 옵션 추가 내용이 상품 수정 화면에 반영되지 않았습니다.")
                if option_page is not None and not option_page.is_closed():
                    await option_page.close()
                    option_page = None
        if preview:
            return _message(applied, True)
        if not title and price is None and not missing_options:
            return {**_message(applied, False), "alreadyProcessed": True}
        await editor.locator('a[href*="formSubmit(\'update\')"]').click()
        await page.wait_for_timeout(5000)
        if missing_options:
            _, verify_link = await ownerclan_status._search_product(page, product_code, account)
            verify_editor = await ownerclan_status._open_editor(page, verify_link)
            try:
                verify_options = await ownerclan_status._open_option_editor(verify_editor)
                try:
                    first = verify_options.locator(".opValName1")
                    second = verify_options.locator(".opValName2")
                    stored = [
                        (
                            await first.nth(index).input_value(),
                            await second.nth(index).input_value() if index < await second.count() else "",
                        )
                        for index in range(await first.count())
                    ]
                    if any(not _pair_exists(stored, pair) for pair in missing_options):
                        raise RuntimeError("오너클랜 저장 후 새 옵션을 확인하지 못했습니다.")
                finally:
                    if not verify_options.is_closed():
                        await verify_options.close()
            finally:
                if not verify_editor.is_closed():
                    await verify_editor.close()
        return _message(applied, False)
    finally:
        if option_page is not None and not option_page.is_closed():
            await option_page.close()
        if editor is not None and not editor.is_closed():
            await editor.close()
        await page.close()


async def _onchannel(browser: Browser, site_code: str, product_code: str, changes: dict[str, Any], preview: bool) -> dict[str, Any]:
    from order_worker.sites.onchannel_registration import _select_address

    account_code = "onch3" if site_code == "onchannel" else site_code
    account = next((item for item in ONCHANNEL_ACCOUNTS if item[0] == account_code), None)
    if account is None:
        raise RuntimeError(f"온채널 계정 설정이 없습니다: {site_code}")
    page = await browser.new_page()
    editor = None
    try:
        await onchannel_status._login(page, account)
        row = await onchannel_status._search(page, product_code)
        edit_button = row.locator(".btn-modi-product")
        if await edit_button.count() == 0 and await row.locator(".btn-modi-cancel").count():
            return {
                "success": True,
                "alreadyProcessed": True,
                "approvalPending": True,
                "verified": True,
                "message": "기존 상품 수정 요청이 온채널 승인 대기 중입니다.",
            }
        async with page.expect_popup(timeout=15000) as popup_info:
            await edit_button.click()
        editor = await popup_info.value
        await editor.wait_for_load_state("domcontentloaded")
        editor.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        applied: list[str] = []
        title = _title(changes, site_code)
        price = _price(changes, site_code)
        requested_options = _option_pairs(changes, site_code)
        if title:
            await editor.locator('input[name="product_nm"]').fill(title)
            applied.append("상품명")
        options_tab_open = False
        if price is not None or requested_options:
            await editor.get_by_role("button", name="가격/옵션 정보 입력", exact=True).click(no_wait_after=True)
            await editor.wait_for_timeout(300)
            options_tab_open = True
        if price is not None:
            select_all = editor.locator("#allChk")
            if await select_all.count() != 1:
                raise RuntimeError("온채널 상품 수정 화면에서 옵션 전체 선택 체크박스를 찾지 못했습니다.")
            await select_all.check()
            price_fields = editor.locator('input[name^="options["][name$="[onch_price]"]')
            if await price_fields.count() == 0:
                raise RuntimeError("온채널 상품 수정 화면에서 기존 옵션 공급가 입력란을 찾지 못했습니다.")
            for index in range(await price_fields.count()):
                await price_fields.nth(index).fill(str(price))
            applied.append("공급가")
        missing_options: list[tuple[str, str]] = []
        if requested_options:
            option_names = editor.locator('input[name^="options["][name$="[option_nm]"]')
            existing_labels = [await option_names.nth(index).input_value() for index in range(await option_names.count())]
            missing_options = [
                pair for pair in requested_options
                if not any(option_matches("/".join(pair), label) for label in existing_labels)
            ]
            applied.append(f"옵션 {'추가 ' + str(len(missing_options)) + '개' if missing_options else '이미 존재'}")
            if not preview:
                existing_prices = editor.locator('input[name^="options["][name$="[onch_price]"]')
                default_price = str(price) if price is not None else (
                    (await existing_prices.first.input_value()).replace(",", "") if await existing_prices.count() else "0"
                )
                for color, size in missing_options:
                    label = f"{color} / {size}"
                    before = await option_names.count()
                    await editor.locator('input[name="option_nm"]').fill(label)
                    new_price = editor.locator('input[name="onch_price"]')
                    if await new_price.count() == 0:
                        raise RuntimeError("온채널 새 옵션 공급가 입력란을 찾지 못했습니다.")
                    await new_price.fill(default_price)
                    await editor.locator("#addOption").click()
                    await editor.wait_for_timeout(250)
                    if await option_names.count() != before + 1:
                        raise RuntimeError(f"온채널 새 옵션이 목록에 생성되지 않았습니다: {label}")
        if preview:
            return _message(applied, True)
        if not title and price is None and not missing_options:
            return {**_message(applied, False), "alreadyProcessed": True}
        basic_step = editor.get_by_role("link", name="기본 정보 입력", exact=True)
        if await basic_step.count():
            await basic_step.click(no_wait_after=True)
            await editor.wait_for_timeout(250)
        comment = editor.locator('textarea[name="modi_comment"]')
        if await comment.count() and not (await comment.input_value()).strip():
            await comment.evaluate(
                "(element, value) => { element.value = value; element.dispatchEvent(new Event('input', {bubbles:true})); element.dispatchEvent(new Event('change', {bubbles:true})); }",
                "상품 옵션 및 정보 수정",
            )
        for button_selector, target_name in (
            ("#search_release_address_btn", "extends_release_address"),
            ("#search_return_address_btn", "extends_return_address"),
        ):
            address = editor.locator(f'input[name="{target_name}"]')
            if await address.count() and not (await address.input_value()).strip():
                await _select_address(editor, button_selector, target_name, "남천로 31")
        kc_type = editor.locator('select[name="kc_type"]')
        if await kc_type.count() and not await kc_type.input_value():
            await kc_type.select_option(label="해당사항없음")
        manufactured = editor.locator('input[name="make_ymd"]')
        if await manufactured.count() and not (await manufactured.input_value()).strip():
            await manufactured.fill("상세페이지참고")
        if options_tab_open:
            await editor.get_by_role("button", name="가격/옵션 정보 입력", exact=True).click(no_wait_after=True)
            await editor.wait_for_timeout(250)
        # The edit popup exposes the action visually as "승인 요청", but its
        # accessibility name is not stable. The site-owned class is the
        # reliable selector on the live form.
        save = editor.locator("button.btn-approve-request:visible").last
        if await save.count() == 0 and not options_tab_open:
            # Title-only edits stay on the basic-information tab, where the
            # final action is rendered but hidden. Move to the second step.
            await editor.get_by_role("button", name="가격/옵션 정보 입력", exact=True).click(no_wait_after=True)
            await editor.wait_for_timeout(300)
            save = editor.locator("button.btn-approve-request:visible").last
        if await save.count() == 0:
            raise RuntimeError("온채널 상품 수정 저장 버튼을 찾지 못했습니다.")
        await save.click()
        await editor.wait_for_timeout(1800)
        if missing_options:
            verify_row = await onchannel_status._search(page, product_code)
            verify_button = verify_row.locator(".btn-modi-product")
            if await verify_button.count() == 0 and await verify_row.locator(".btn-modi-cancel").count():
                return {
                    **_message(applied, False),
                    "approvalRequested": True,
                    "message": f"온채널 수정 승인 요청 완료: {', '.join(applied)}",
                }
            async with page.expect_popup(timeout=15000) as popup_info:
                await verify_button.click()
            verify_editor = await popup_info.value
            try:
                await verify_editor.wait_for_load_state("domcontentloaded")
                await verify_editor.get_by_role("button", name="가격/옵션 정보 입력", exact=True).click(no_wait_after=True)
                await verify_editor.wait_for_timeout(300)
                verify_names = verify_editor.locator('input[name^="options["][name$="[option_nm]"]')
                stored = [await verify_names.nth(index).input_value() for index in range(await verify_names.count())]
                if any(not any(option_matches("/".join(pair), label) for label in stored) for pair in missing_options):
                    raise RuntimeError("온채널 저장 후 새 옵션을 확인하지 못했습니다.")
            finally:
                if not verify_editor.is_closed():
                    await verify_editor.close()
        return _message(applied, False)
    finally:
        if editor is not None and not editor.is_closed():
            await editor.close()
        await page.close()


async def _domeggook(
    browser: Browser,
    site_code: str,
    product_code: str,
    changes: dict[str, Any],
    preview: bool,
    *,
    search_code: str | None = None,
) -> dict[str, Any]:
    account = next((item for item in DOMEGGOOK_ACCOUNTS if item[0] == site_code), None)
    if account is None:
        raise RuntimeError(f"도매꾹 계정 설정이 없습니다: {site_code}")
    page = await browser.new_page(viewport={"width": 1800, "height": 1200})
    page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
    try:
        await domeggook_status._login(page, account)
        # The F account stores the external product code (for example F007780)
        # in the grid, but its management search matches the original G-code in
        # the product title. Search by the original code, then identify the row
        # using the external code shown in the result grid.
        lookup_code = search_code or product_code
        if lookup_code == product_code:
            row_key = await domeggook_status._search(page, product_code)
        else:
            await page.goto(domeggook_status.MANAGEMENT_URL, wait_until="networkidle")
            await page.locator('input[name="ttl"]').fill(lookup_code)
            await page.locator('input[type="submit"]').click()
            await page.wait_for_timeout(1800)
            cells = page.locator('td[data-column-name="code"]').filter(has_text=product_code)
            exact = [
                cell
                for cell in await cells.all()
                if (await cell.inner_text()).strip() == product_code
            ]
            if not exact:
                raise ProductNotFound(product_code)
            if len(exact) != 1:
                raise RuntimeError(f"도매꾹: 상품코드 {product_code} 검색 결과를 1건으로 확인하지 못해 처리하지 않았습니다.")
            row_key = await exact[0].get_attribute("data-row-key") or "0"
        item_no = (await page.locator(f'td[data-row-key="{row_key}"][data-column-name="no"]').inner_text()).strip()
        applied: list[str] = []
        title = _title(changes, site_code)
        price = _price(changes, site_code)
        requested_options = _option_pairs(changes, site_code)
        missing_options: list[tuple[str, str]] = []
        if requested_options:
            await page.locator('.tui-grid-rside-area .tui-grid-body-area').evaluate("e => e.scrollLeft = 800")
            await page.wait_for_timeout(350)
            option_cell = page.locator(f'td[data-row-key="{row_key}"][data-column-name="useOpt"]')
            if await option_cell.count() != 1:
                raise RuntimeError("도매꾹 주문옵션 사용여부 칸을 찾지 못했습니다.")
            async with page.expect_popup(timeout=15000) as popup_info:
                await option_cell.locator("a").click()
            popup = await popup_info.value
            await popup.wait_for_load_state("domcontentloaded")
            try:
                value_fields = popup.locator('input[name="optValue[]"]')
                values = [
                    [part.strip() for part in (await value_fields.nth(index).input_value()).split(",") if part.strip()]
                    for index in range(await value_fields.count())
                ]
                existing = (
                    [(color, "") for color in values[0]] if len(values) == 1
                    else [(color, size) for color in values[0] for size in values[1]] if len(values) >= 2
                    else []
                )
                missing_options = [pair for pair in requested_options if not _pair_exists(existing, pair)]
                applied.append(f"옵션 {'추가 ' + str(len(missing_options)) + '개' if missing_options else '이미 존재'}")
                if not preview and missing_options:
                    if len(values) < 2:
                        raise RuntimeError("도매꾹 상품의 기존 옵션이 색상/사이즈 2단계 형식이 아닙니다.")
                    prior: dict[str, tuple[str, str]] = {}
                    qty_fields = popup.locator('input[name="qty[]"]')
                    status_fields = popup.locator('select[name="hid[]"]')
                    for index, pair in enumerate(existing):
                        prior[normalize("/".join(pair))] = (
                            await qty_fields.nth(index).input_value() if index < await qty_fields.count() else "9999",
                            await status_fields.nth(index).input_value() if index < await status_fields.count() else "0",
                        )
                    for color, size in missing_options:
                        if not any(normalize(color) == normalize(value) for value in values[0]):
                            values[0].append(color)
                        if not any(normalize(size) == normalize(value) for value in values[1]):
                            values[1].append(size)
                    price_fields = popup.locator('input[name="optPrice[]"]')
                    for index, dimension_values in enumerate(values[:2]):
                        await value_fields.nth(index).fill(",".join(dimension_values))
                        if index < await price_fields.count():
                            await price_fields.nth(index).fill(",".join("0" for _ in dimension_values))
                    await popup.locator("img[onclick=\"checkOptType()\"]").click()
                    await popup.wait_for_timeout(700)
                    generated = [(color, size) for color in values[0] for size in values[1]]
                    qty_fields = popup.locator('input[name="qty[]"]')
                    status_fields = popup.locator('select[name="hid[]"]')
                    if await qty_fields.count() != len(generated):
                        raise RuntimeError("도매꾹 새 옵션 조합이 예상 개수대로 생성되지 않았습니다.")
                    for index, pair in enumerate(generated):
                        old_qty, old_status = prior.get(normalize("/".join(pair)), ("9999", "0"))
                        await qty_fields.nth(index).fill(old_qty.replace(",", "") or "9999")
                        if index < await status_fields.count():
                            await status_fields.nth(index).select_option(old_status)
                    await popup.locator('img[onclick*="endOptSet"]').last.click()
                    if not popup.is_closed():
                        await popup.wait_for_event("close", timeout=10000)
            finally:
                if not popup.is_closed():
                    await popup.close()
            if not preview and missing_options:
                await page.wait_for_timeout(1200)
                await page.locator('.tui-grid-rside-area .tui-grid-body-area').evaluate("e => e.scrollLeft = 800")
                async with page.expect_popup(timeout=15000) as verify_info:
                    await page.locator(f'td[data-row-key="{row_key}"][data-column-name="useOpt"] a').click()
                verify_popup = await verify_info.value
                try:
                    await verify_popup.wait_for_load_state("domcontentloaded")
                    verify_values = await verify_popup.locator('input[name="optValue[]"]').evaluate_all(
                        "es => es.map(e => e.value.split(',').map(v => v.trim()).filter(Boolean))"
                    )
                    stored = [(color, size) for color in verify_values[0] for size in verify_values[1]] if len(verify_values) >= 2 else []
                    if any(not _pair_exists(stored, pair) for pair in missing_options):
                        raise RuntimeError("도매꾹 저장 후 새 옵션을 확인하지 못했습니다.")
                finally:
                    if not verify_popup.is_closed():
                        await verify_popup.close()
        if not title and price is None:
            if preview:
                return _message(applied, True)
            if not missing_options:
                return {**_message(applied, False), "alreadyProcessed": True}
            return _message(applied, False)
        await page.goto(f"https://www.domeggook.com/sc/item/editFrm/{item_no}", wait_until="domcontentloaded")
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
        requested_options = _option_pairs(changes, site_code)
        if title:
            await page.locator('input[name="gname"]').fill(title)
            applied.append("상품명")
        if price is not None:
            await page.locator("#supply_price").fill(str(price))
            applied.append("공급가격")
        missing_options: list[tuple[str, str]] = []
        if requested_options:
            option_ids = page.locator('#sit_option_frm input[name="opt_id[]"]')
            existing = []
            for index in range(await option_ids.count()):
                parts = [part.strip() for part in (await option_ids.nth(index).input_value()).split("\x1e")]
                if len(parts) >= 2:
                    existing.append((parts[0], parts[1]))
            missing_options = [pair for pair in requested_options if not _pair_exists(existing, pair)]
            applied.append(f"옵션 {'추가 ' + str(len(missing_options)) + '개' if missing_options else '이미 존재'}")
            if not preview and missing_options:
                prior: dict[str, tuple[str, str, str]] = {}
                supplies = page.locator('#sit_option_frm input[name="opt_supply_price[]"]')
                stocks = page.locator('#sit_option_frm input[name="opt_stock_qty[]"]')
                uses = page.locator('#sit_option_frm select[name="opt_use[]"]')
                for index, pair in enumerate(existing):
                    prior[normalize("/".join(pair))] = (
                        await supplies.nth(index).input_value(),
                        await stocks.nth(index).input_value(),
                        await uses.nth(index).input_value(),
                    )
                colors = [part.strip() for part in (await page.locator("#opt1").input_value()).split(",") if part.strip()]
                sizes = [part.strip() for part in (await page.locator("#opt2").input_value()).split(",") if part.strip()]
                for color, size in missing_options:
                    if not any(normalize(color) == normalize(value) for value in colors):
                        colors.append(color)
                    if not any(normalize(size) == normalize(value) for value in sizes):
                        sizes.append(size)
                await page.locator("#opt1").fill(",".join(colors))
                await page.locator("#opt2").fill(",".join(sizes))
                await page.locator("#option_table_create").click()
                await page.wait_for_timeout(500)
                option_ids = page.locator('#sit_option_frm input[name="opt_id[]"]')
                supplies = page.locator('#sit_option_frm input[name="opt_supply_price[]"]')
                stocks = page.locator('#sit_option_frm input[name="opt_stock_qty[]"]')
                uses = page.locator('#sit_option_frm select[name="opt_use[]"]')
                if await option_ids.count() != len(colors) * len(sizes):
                    raise RuntimeError("스페셜오퍼 새 옵션 조합이 예상 개수대로 생성되지 않았습니다.")
                for index in range(await option_ids.count()):
                    pair = tuple((await option_ids.nth(index).input_value()).split("\x1e")[:2])
                    old_supply, old_stock, old_use = prior.get(normalize("/".join(pair)), ("0", "9999", "1"))
                    await supplies.nth(index).fill(old_supply.replace(",", "") or "0")
                    await stocks.nth(index).fill(old_stock.replace(",", "") or "9999")
                    await uses.nth(index).select_option(old_use)
        if preview:
            return _message(applied, True)
        if not title and price is None and not missing_options:
            return {**_message(applied, False), "alreadyProcessed": True}
        if await page.locator("#modify_status").count():
            if missing_options:
                choices = await page.locator("#modify_status option").evaluate_all(
                    "es => es.map(e => ({value:e.value, text:(e.textContent || '').trim()}))"
                )
                option_change = next((choice for choice in choices if "옵션변경" in choice["text"]), None)
                await page.locator("#modify_status").select_option(option_change["value"] if option_change else "9")
            else:
                await page.locator("#modify_status").select_option("9")
        if await page.locator('textarea[name="modify_msg_after"]').count():
            await page.locator('textarea[name="modify_msg_after"]').fill(".")
        save = page.get_by_role("button", name="저장", exact=True)
        if await save.count() == 0:
            raise RuntimeError("스페셜오퍼 상품 수정 저장 버튼을 찾지 못했습니다.")
        await save.click()
        await specialoffer_status._click_visible_confirm(page)
        await page.wait_for_timeout(1800)
        if missing_options:
            verify_row = await specialoffer_status._search(page, product_code)
            verify_href = await verify_row.locator('a[href*="seller_goods_form"]').get_attribute("href")
            if not verify_href:
                raise RuntimeError("스페셜오퍼 저장 검증용 상품 수정 주소를 찾지 못했습니다.")
            await page.goto(urljoin(page.url, verify_href), wait_until="domcontentloaded")
            verify_ids = page.locator('#sit_option_frm input[name="opt_id[]"]')
            stored = []
            for index in range(await verify_ids.count()):
                parts = (await verify_ids.nth(index).input_value()).split("\x1e")
                if len(parts) >= 2:
                    stored.append((parts[0], parts[1]))
            if any(not _pair_exists(stored, pair) for pair in missing_options):
                raise RuntimeError("스페셜오퍼 저장 후 새 옵션을 확인하지 못했습니다.")
        return _message(applied, False)
    finally:
        await page.close()


async def _domesin(browser: Browser, site_code: str, product_code: str, changes: dict[str, Any], preview: bool) -> dict[str, Any]:
    page = await browser.new_page()
    page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
    option_page = None
    try:
        await domesin_status._login(page)
        item_id = await domesin_status._search(page, product_code)
        applied: list[str] = []
        title = _title(changes, site_code).replace("_", " ")
        price = _price(changes, site_code)
        requested_options = _option_pairs(changes, site_code)
        if title:
            await page.locator(f'input[name="iname_{item_id}"]').fill(title)
            applied.append("상품명")
        if price is not None:
            await page.locator(f'input[name="cost_{item_id}"]').fill(str(price))
            applied.append("판매가")
        missing_options: list[tuple[str, str]] = []
        if requested_options:
            async with page.expect_popup(timeout=15000) as popup_info:
                await page.locator(f'input[onclick="item_option({item_id});"]').click()
            option_page = await popup_info.value
            await option_page.wait_for_load_state("domcontentloaded")
            first = option_page.locator('input[name="op_n1[]"]')
            second = option_page.locator('input[name="op_n2[]"]')
            existing = [
                (
                    await first.nth(index).input_value(),
                    await second.nth(index).input_value() if index < await second.count() else "",
                )
                for index in range(await first.count())
            ]
            missing_options = [pair for pair in requested_options if not _pair_exists(existing, pair)]
            applied.append(f"옵션 {'추가 ' + str(len(missing_options)) + '개' if missing_options else '이미 존재'}")
            if not preview and missing_options:
                for color, size in missing_options:
                    before = await first.count()
                    await option_page.locator('input[onclick="add_option();"]').click()
                    await option_page.wait_for_timeout(150)
                    if await first.count() != before + 1:
                        raise RuntimeError("도매의신 새 옵션 입력 행이 생성되지 않았습니다.")
                    await first.nth(before).fill(color)
                    await second.nth(before).fill(size)
                    for name in ("op_cost[]", "op_limit_amount[]", "op_basic_price[]"):
                        field = option_page.locator(f'input[name="{name}"]').nth(before)
                        if await field.count():
                            await field.fill("0")
                    status = option_page.locator('select[name="op_sold[]"]').nth(before)
                    if await status.count():
                        await status.select_option("0")
                await option_page.locator('input[type="submit"][value="상품 옵션정보 수정하기"]').click()
                await page.wait_for_timeout(1500)
            if option_page is not None and not option_page.is_closed():
                await option_page.close()
                option_page = None
            if not preview and missing_options:
                async with page.expect_popup(timeout=15000) as verify_info:
                    await page.locator(f'input[onclick="item_option({item_id});"]').click()
                verify_page = await verify_info.value
                try:
                    await verify_page.wait_for_load_state("domcontentloaded")
                    verify_first = verify_page.locator('input[name="op_n1[]"]')
                    verify_second = verify_page.locator('input[name="op_n2[]"]')
                    stored = [
                        (
                            await verify_first.nth(index).input_value(),
                            await verify_second.nth(index).input_value() if index < await verify_second.count() else "",
                        )
                        for index in range(await verify_first.count())
                    ]
                    if any(not _pair_exists(stored, pair) for pair in missing_options):
                        raise RuntimeError("도매의신 저장 후 새 옵션을 확인하지 못했습니다.")
                finally:
                    if not verify_page.is_closed():
                        await verify_page.close()
        if preview:
            return _message(applied, True)
        if not title and price is None:
            if not missing_options:
                return {**_message(applied, False), "alreadyProcessed": True}
            return _message(applied, False)
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
        if option_page is not None and not option_page.is_closed():
            await option_page.close()
        await page.close()


async def _namdo(browser: Browser, site_code: str, product_code: str, changes: dict[str, Any], preview: bool) -> dict[str, Any]:
    from order_worker.sites.namdo_registration import _login, _select_colors, _select_sizes

    page = await browser.new_page(viewport={"width": 1800, "height": 1200})
    try:
        await _login(page)
        await namdo_status._open_edit(page, product_code)
        applied: list[str] = []
        title = _title(changes, site_code)
        price = _price(changes, site_code)
        requested_options = _option_pairs(changes, site_code)
        if title:
            await page.get_by_placeholder("상품명 입력 해주세요", exact=True).fill(title)
            applied.append("상품명")
        if price is not None:
            option_section = page.get_by_text("옵션 상세 수정", exact=True).locator("xpath=ancestor::section[1]")
            if await option_section.count() != 1:
                raise RuntimeError("남도마켓 옵션 상세 수정 영역을 찾지 못했습니다.")
            price_fields = option_section.get_by_placeholder("판매 가격을 입력해주세요.", exact=True)
            if await price_fields.count() == 0:
                raise RuntimeError("남도마켓 옵션가격 입력란을 찾지 못했습니다.")
            for index in range(await price_fields.count()):
                await price_fields.nth(index).fill(str(price))
            applied.append(f"옵션가격 {await price_fields.count()}개")
        missing_options: list[tuple[str, str]] = []
        if requested_options:
            option_section = page.get_by_text("옵션 상세 수정", exact=True).locator("xpath=ancestor::section[1]")
            existing: list[tuple[str, str]] = []
            containers = option_section.locator(".option-container")
            for container_index in range(await containers.count()):
                container = containers.nth(container_index)
                color = (await container.locator(".color-box").first.inner_text()).strip()
                rows = container.locator("tr:has(td.size-box)")
                for row_index in range(await rows.count()):
                    existing.append((color, (await rows.nth(row_index).locator("td.size-box").inner_text()).strip()))
            missing_options = [pair for pair in requested_options if not _pair_exists(existing, pair)]
            applied.append(f"옵션 {'추가 ' + str(len(missing_options)) + '개' if missing_options else '이미 존재'}")
            if not preview and missing_options:
                existing_colors = {normalize(color) for color, _ in existing}
                existing_sizes = {normalize(size) for _, size in existing}
                add_colors = []
                add_sizes = []
                for color, size in missing_options:
                    if normalize(color) not in existing_colors and all(normalize(color) != normalize(value) for value in add_colors):
                        add_colors.append(color)
                    if normalize(size) not in existing_sizes and all(normalize(size) != normalize(value) for value in add_sizes):
                        add_sizes.append(size)
                if add_colors:
                    await _select_colors(page, add_colors)
                if add_sizes:
                    await _select_sizes(page, add_sizes)
                await page.wait_for_timeout(500)
                for pair in missing_options:
                    await namdo_status._find_option(page, "/".join(pair))
        if preview:
            return _message(applied, True)
        if not title and price is None and not missing_options:
            return {**_message(applied, False), "alreadyProcessed": True}
        save = page.get_by_role("button", name="수정하기", exact=True)
        if await save.count() != 1:
            raise RuntimeError("남도마켓 상품 수정 저장 버튼을 찾지 못했습니다.")
        await save.click()
        await page.wait_for_timeout(1800)
        if missing_options:
            await namdo_status._open_edit(page, product_code)
            for pair in missing_options:
                await namdo_status._find_option(page, "/".join(pair))
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
    "cafe_laf": laf.run_edit,
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
    site_references = request.get("siteReferences") if isinstance(request.get("siteReferences"), dict) else {}
    results = list(request.get("preResults") or [])
    if "cafe_laf" in sites:
        site_code = "cafe_laf"
        product_code = str(site_codes.get(site_code) or request.get("productCode") or "").strip()
        if on_progress:
            on_progress(site_code, results.copy())
        try:
            result = await asyncio.wait_for(
                laf.run_edit(
                    None,
                    site_code,
                    product_code,
                    changes,
                    preview,
                    article_url=str(site_references.get(site_code) or "").strip() or None,
                ),
                timeout=240,
            )
            results.append({"site": LABELS[site_code], "siteCode": site_code, "productCode": product_code, **result})
        except Exception as exc:
            results.append(failed(LABELS[site_code], site_code, "product-edit", product_code, exc))
        if on_progress:
            on_progress(None, results.copy())
        sites = [value for value in sites if value != site_code]
    if not sites:
        return results
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
                    if site_code == "Fdomeggook":
                        result = await asyncio.wait_for(
                            _domeggook(
                                browser,
                                site_code,
                                product_code,
                                changes,
                                preview,
                                search_code=str(request.get("productCode") or "").strip() or None,
                            ),
                            timeout=240,
                        )
                    else:
                        result = await asyncio.wait_for(runner(browser, site_code, product_code, changes, preview), timeout=240)
                    results.append({"site": LABELS.get(site_code, site_code), "siteCode": site_code, "productCode": product_code, **result})
                except Exception as exc:
                    if _is_product_not_found_error(exc):
                        results.append(product_not_found(LABELS.get(site_code, site_code), site_code, "product-edit", product_code))
                    else:
                        results.append(failed(LABELS.get(site_code, site_code), site_code, "product-edit", product_code, exc))
                if on_progress:
                    on_progress(None, results.copy())
        finally:
            await browser.close()
    return results
