from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs
from zoneinfo import ZoneInfo

import requests
from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.onchannel import ACCOUNTS, dismiss_popups


LOGIN_URL = "https://www.onch3.co.kr/login/login_web.php"
REGISTER_LIST_URL = "https://www.onch3.co.kr/pending_products_management.php"
REGISTER_URL = "https://www.onch3.co.kr/regist_pending_products.php"
MANAGEMENT_URL = "https://www.onch3.co.kr/products_management.php"
LABELS = {"onch3": "온채널", "Fonch3": "F온채널"}


def _contains_product_code(text: str, product_code: str) -> bool:
    return bool(product_code and re.search(rf"(?<![A-Za-z0-9]){re.escape(product_code)}(?![A-Za-z0-9])", text, re.IGNORECASE))


async def _matching_product_row(page: Page, product_code: str):
    # Only actual product rows count, never page headings/search terms.
    rows = page.locator("table tbody tr").filter(has_text=product_code)
    for index in range(await rows.count()):
        row = rows.nth(index)
        if _contains_product_code(await row.inner_text(), product_code):
            return row
    return None


def _account(account_code: str):
    return next((account for account in ACCOUNTS if account[0] == account_code), None)


async def _login(page: Page, account) -> None:
    _, user_id, password, label = account
    print(f"PROGRESS: [{label}] 상품등록 로그인 중...")
    page.set_default_timeout(12000)
    page.set_default_navigation_timeout(20000)
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await page.fill('input[name="username"]', user_id)
    await page.fill('input[name="password"]', password)
    await page.click("button.submit-btn")
    await page.wait_for_url(lambda url: "/login/" not in url, timeout=30000)
    await dismiss_popups(page)


async def _goto(page: Page, url: str) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded")
    except Exception as exc:
        if "interrupted by another navigation" not in str(exc):
            raise
        # A successful draft-save redirect may still be completing. Retry only
        # this read-only navigation, never the save request.
        await page.wait_for_load_state("domcontentloaded")
        await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(700)
    await dismiss_popups(page)


async def _select_text(page: Page, selector: str, text: str) -> None:
    select = page.locator(selector).first
    options = await select.locator("option").evaluate_all(
        "els => els.map(o => ({value:o.value,text:(o.textContent||'').trim()}))"
    )
    match = next((item for item in options if item["text"] == text), None)
    if not match:
        raise RuntimeError(f"온채널 선택값을 찾지 못했습니다: {text}")
    await select.select_option(str(match["value"]))
    await page.wait_for_timeout(250)


async def _registered_product_exists(page: Page, product_code: str) -> bool:
    await _goto(page, MANAGEMENT_URL)
    search_type = page.locator('select[name="search_type"]').first
    if await search_type.count() == 0:
        return False
    await search_type.select_option("product_name")
    await page.locator('input[name="search_text"]').first.fill(product_code)
    await page.locator("#searchForm button[type=submit]").click()
    await page.wait_for_load_state("domcontentloaded")
    await page.wait_for_timeout(400)
    return await _matching_product_row(page, product_code) is not None


async def _draft_exists(page: Page, product_code: str) -> bool:
    pending = [f"{REGISTER_LIST_URL}?status=N&regSec=N"]
    visited: set[str] = set()
    while pending:
        if len(visited) >= 50:
            raise RuntimeError("온채널 임시저장 목록이 50페이지를 초과했습니다. 중복 방지를 위해 직접 확인해 주세요.")
        url = pending.pop(0)
        if url in visited:
            continue
        visited.add(url)
        await _goto(page, url)
        if await _matching_product_row(page, product_code) is not None:
            return True
        links = await page.locator('a[href]').evaluate_all("els => els.filter(e => /^\\d+$/.test(e.textContent.trim())).map(e => e.href)")
        for link in links:
            parsed = urlparse(link)
            query = parse_qs(parsed.query)
            if (parsed.netloc == "www.onch3.co.kr" and parsed.path == "/pending_products_management.php"
                    and query.get("status", ["N"])[0] == "N" and query.get("regSec", ["N"])[0] == "N"
                    and link not in visited and link not in pending):
                pending.append(link)
    return False


async def _verified_draft_result(page: Page, request: dict[str, Any], account: dict[str, Any], already: bool = False) -> dict[str, Any]:
    code = str(account["code"])
    row = await _matching_product_row(page, code)
    if row is None:
        raise RuntimeError("온채널 임시저장 상품 행을 확인하지 못했습니다.")
    row_text = await row.inner_text()
    draft_id = await row.get_by_role("button", name="수정", exact=True).get_attribute("data-id")
    if not draft_id or not draft_id.isdigit():
        raise RuntimeError("온채널 임시저장 수정 ID를 확인하지 못했습니다.")
    url = f"{REGISTER_URL}?id={draft_id}"
    await _goto(page, url)
    if await page.locator('input[name="product_jejo_code"]').input_value() != code:
        raise RuntimeError("온채널 저장된 공급사 코드가 요청 상품과 다릅니다.")
    if await page.locator('input[name="product_name"]').input_value() != str(account["productName"]):
        raise RuntimeError("온채널 저장된 상품명이 요청과 다릅니다. 기존 임시저장을 직접 확인해 주세요.")
    saved_options = await page.locator('input[name$="[option_nm]"]').evaluate_all("els=>els.map(e=>e.value)")
    requested_options = request.get("options") or [code]
    normalize = lambda value: re.sub(r"\s+", "", str(value))
    if sorted(map(normalize, saved_options)) != sorted(map(normalize, requested_options)):
        raise RuntimeError("온채널 저장된 옵션이 요청과 일치하지 않습니다.")
    prices = await page.locator('input[name$="[onch_price]"]').evaluate_all("els=>els.map(e=>Number(e.value))")
    if len(prices) != len(saved_options) or any(price != int(account["supplyPrice"]) for price in prices):
        raise RuntimeError("온채널 저장된 옵션 공급가가 요청과 다릅니다.")
    for name in ("product_img", "product_img_550", "product_img_300", "product_img_130"):
        if not await page.locator(f'input[name="{name}_url"]').input_value():
            raise RuntimeError(f"온채널 저장된 대표이미지를 확인하지 못했습니다: {name}")
    expected_images = len(request.get("detailImages") or []) + len(request.get("sizeImages") or [])
    detail_count = await page.locator(".ck-content img").count()
    if expected_images and detail_count < expected_images:
        raise RuntimeError("온채널 저장된 상세페이지 이미지가 누락됐습니다.")
    site_code = str(account["siteCode"])
    platform_code = re.search(r"\bCH\d+\b", row_text)
    registration_date = re.search(r"\b\d{4}-\d{2}-\d{2}\b", row_text)
    expiry = ((datetime.strptime(registration_date.group(), "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d") + " 23:59 KST") if registration_date else "등록 다음 날 23:59 KST"
    return {"site": LABELS[site_code], "siteCode": site_code, "success": True, "draftSaved": True,
            "alreadyDraft": already, "productCode": code, "draftId": draft_id, "draftUrl": url,
            "siteProductCode": platform_code.group() if platform_code else None, "verified": True,
            "verifiedAt": datetime.now(ZoneInfo("Asia/Seoul")).isoformat(), "draftExpiresAt": expiry,
            "message": f"{'기존 임시저장' if already else '임시저장'} 확인 완료: {code} · {platform_code.group() if platform_code else draft_id} · 옵션/가격/이미지 재조회 검증 · {expiry} 자동 삭제 예정(기한 내 직접 승인요청)"}


def _download_images(account: dict[str, Any], target_dir: Path) -> list[Path]:
    items = account.get("galleryImages") or [account["mainImage"], *account.get("additionalImages", [])]
    # Reject stale queued requests that mixed detail images into representative slots.
    if any("/intra_image/" not in str(item.get("url", "")) or "1000" not in str(item.get("fileName", "")) for item in items[:4]):
        raise RuntimeError("온채널 대표이미지는 image2의 1000 대표컷만 사용할 수 있습니다. 최신 상품정보로 다시 요청해 주세요.")
    paths: list[Path] = []
    for index, item in enumerate(items[:4]):
        file_name = Path(str(item.get("fileName") or f"image-{index}.jpg")).name
        target = target_dir / f"{index:02d}-{file_name}"
        response = requests.get(str(item["url"]), timeout=45)
        response.raise_for_status()
        target.write_bytes(response.content)
        paths.append(target)
    if not paths:
        raise RuntimeError("온채널에 등록할 대표이미지가 없습니다.")
    return paths


async def _select_category(page: Page, category_path: list[str]) -> None:
    selectors = [
        'select[name="category_cate_first"]',
        'select[name="category_cate_second"]',
        'select[name="category_cate_third"]',
        'select[name="category_cate_fourth"]',
    ]
    for selector, label in zip(selectors, category_path):
        if label:
            await _select_text(page, selector, label)


async def _select_address(page: Page, button_selector: str, target_name: str, keyword: str) -> None:
    await page.locator(button_selector).click()
    modal = page.locator(".modal:visible")
    await modal.wait_for(state="visible")
    await modal.locator("#search_type").select_option("address")
    await modal.locator("#search_text").fill(keyword)
    await modal.locator("#searchButton").click()
    await page.wait_for_timeout(500)
    rows = modal.locator("#addressList tr").filter(has_text=keyword)
    if await rows.count() != 1:
        raise RuntimeError(f"온채널 주소지 '{keyword}' 검색 결과를 1건으로 찾지 못했습니다.")
    await rows.first.locator('input[name="address-checkbox"]').check()
    await modal.locator("#selectCompleteButton").click()
    await modal.wait_for(state="hidden")
    address = await page.locator(f'input[name="{target_name}"]').input_value()
    if keyword not in address:
        raise RuntimeError(f"온채널 주소지가 입력되지 않았습니다: {target_name}")


async def _keep_requested_category(page: Page) -> None:
    keep = page.get_by_role("button", name="유지하기")
    try:
        await keep.wait_for(state="visible", timeout=3500)
        await keep.click()
    except Exception:
        pass


async def _set_editor_html(page: Page, html: str) -> None:
    source_button = page.get_by_role("button", name="Source", exact=True).first
    await source_button.wait_for(state="visible", timeout=12000)
    source_area = page.locator(".ck-editor textarea:visible").first
    if await source_area.count() == 0:
        await source_button.click()
        await source_area.wait_for(state="visible", timeout=5000)
    await source_area.fill(html)
    saved_html = await source_area.input_value()
    if saved_html != html:
        raise RuntimeError("온채널 Source 입력 영역에 상품상세 이미지 HTML이 반영되지 않았습니다.")
    # Commit source mode to CKEditor's model before changing to the options tab.
    await source_button.click()
    await source_area.wait_for(state="hidden", timeout=5000)


async def _fill_basic_form(
    page: Page,
    request: dict[str, Any],
    account: dict[str, Any],
    image_paths: list[Path],
) -> None:
    await _goto(page, REGISTER_URL)
    if await page.locator('input[name="product_supp_sec"]').count() == 0:
        raise RuntimeError(f"온채널 상품등록 화면에 접근하지 못했습니다: {page.url}")

    await page.locator('input[name="product_supp_sec"][value="1"]').check()
    await page.locator('input[name="product_prd_channel"][value="1"]').check()
    await page.locator('input[name="agree_terms"]').check()
    agree_button = page.locator("#btn-agree")
    if await agree_button.count():
        # October 2026: the tabbed editor became a single section form.
        await page.locator('input[name="modify_agree_terms"]').check()
        await agree_button.click()
    else:
        await page.get_by_role("button", name="상품 기본 정보 입력").click(no_wait_after=True)
    await page.wait_for_timeout(300)

    await _select_category(page, [str(value) for value in request.get("categoryPath", [])])
    await page.locator('input[name="product_name"]').fill(str(account["productName"]))
    keyword_items = request.get("keywordItems") or [
        value.strip() for value in str(request.get("keywords") or "").replace("\n", ",").split(",") if value.strip()
    ]
    keyword_fields = page.locator('input[name="product_subject[]"]')
    for index, keyword in enumerate(keyword_items[: await keyword_fields.count()]):
        await keyword_fields.nth(index).fill(str(keyword))
    await page.locator('input[name="product_sec_tax"][value="N"]').check()
    minor_block = page.locator('input[name="product_prd_char"]')
    if request.get("minorSalesAllowed"):
        await minor_block.uncheck()
    else:
        await minor_block.check()
    await page.locator('input[name="product_jejo_code"]').fill(str(account["code"]))
    await page.locator('input[name="coupang_send"][value="Y"]').check()

    onchannel = request.get("onchannel") or {}
    await _select_text(page, 'select[name="product_trans_nm"]', str(onchannel.get("carrier") or "롯데택배"))
    await page.locator('input[name="extends_send_type"][value="I"]').check()
    await page.locator('input[name="extends_send_price"]').fill(str(onchannel.get("shippingFee") or 3000))
    await page.locator('input[name="extends_jeju_send_price"]').fill(str(onchannel.get("jejuExtraFee") or 3000))
    await page.locator('input[name="extends_etc_send_price"]').fill(str(onchannel.get("islandExtraFee") or 9000))
    shipping_fields = page.locator('input[name="product_trans_info[]"]')
    for index, value in enumerate([
        onchannel.get("shippingCutoff") or "오후2시",
        onchannel.get("shippingOrigin") or "제조사",
        onchannel.get("shippingLeadTime") or "평균1~2일 / 주문폭주,리오더시 개별출고일정 안내",
    ]):
        await shipping_fields.nth(index).fill(str(value))
    await page.locator('input[name="product_return_comment"]').fill(str(onchannel.get("returnGuide") or ""))
    address_keyword = str(onchannel.get("addressKeyword") or "남천로 31")
    await _select_address(page, "#search_release_address_btn", "extends_release_address", address_keyword)
    await _select_address(page, "#search_return_address_btn", "extends_return_address", address_keyword)
    await page.locator('input[name="extends_is_bundle"][value="Y"]').check()

    notice = str(request.get("noticeCategory") or "의류")
    notice_label = "패션잡화(모자/벨트/액세서리)" if notice == "패션잡화" else notice
    await _select_text(page, "#onch_sel_cate", notice_label)
    await page.wait_for_timeout(400)
    notice_values = onchannel.get("notice") or {}
    await page.locator('input[name="main_mat"]').fill(str(notice_values.get("material") or "폴리혼방"))
    await _select_text(page, 'select[name="kc_type"]', str(notice_values.get("kcType") or "해당사항없음"))
    await page.locator('input[name="kc_gov"]').fill(str(notice_values.get("kcAgency") or "해당사항없음"))
    await page.locator('input[name="kc_sec"]').fill(str(notice_values.get("kcNumber") or "해당사항없음"))
    await page.locator('input[name="kc_name"]').fill(str(notice_values.get("kcCompany") or "해당사항없음"))
    await page.locator('input[name="deliver_time"]').fill(str(notice_values.get("deliveryTime") or ""))
    await page.locator('input[name="prd_color"]').fill(str(notice_values.get("color") or "상세페이지참고"))
    await page.locator('input[name="prd_meas"]').fill(str(notice_values.get("size") or "상세페이지참고"))
    await page.locator('input[name="make_import"]').fill(str(notice_values.get("manufacturer") or "조원"))
    await page.locator('input[name="make_con"]').fill(str(notice_values.get("country") or "중국"))
    await page.locator('input[name="wash_bene"]').fill(str(notice_values.get("washing") or ""))
    await page.locator('input[name="make_ymd"]').fill(str(notice_values.get("manufacturedAt") or ""))
    await page.locator('input[name="warr_prov"]').fill(str(notice_values.get("warranty") or ""))
    await page.locator('input[name="as_phone"]').fill(str(account.get("asContact") or ""))

    await _set_editor_html(page, str(request.get("detailHtml") or ""))
    image_fields = ["product_img", "product_img_550", "product_img_300", "product_img_130"]
    for index, field_name in enumerate(image_fields):
        path = image_paths[min(index, len(image_paths) - 1)]
        await page.locator(f'input[name="{field_name}"]').set_input_files(str(path))
        await page.wait_for_timeout(300)
        await _keep_requested_category(page)
    await page.locator('input[name="modify_agree_terms"]').check()


async def _set_options(page: Page, request: dict[str, Any], account: dict[str, Any]) -> None:
    option_tab = page.get_by_role("button", name="가격/옵션 정보 입력")
    if await option_tab.count():
        await option_tab.click(no_wait_after=True)
    await page.wait_for_timeout(300)
    options = [str(value).strip() for value in request.get("options", []) if str(value).strip()]
    if not options:
        options = [str(account["code"])]
    rows = page.locator("#optionList tr, #option-list tr, table tbody tr")
    initial_count = await rows.count()
    for option_name in options:
        await page.locator('input[name="option_nm"]').fill(option_name)
        await page.locator('input[name="onch_price"]').fill(str(account["supplyPrice"]))
        await page.locator("#addOption").click()
        await page.wait_for_timeout(250)
    if await rows.count() <= initial_count:
        body_text = await page.locator("body").inner_text()
        if not all(option in body_text for option in options):
            raise RuntimeError("온채널 옵션 조합이 상품정보에 반영되지 않았습니다.")


async def run_account(request: dict[str, Any], account_payload: dict[str, Any], preview: bool = False) -> dict[str, Any]:
    site_code = str(account_payload.get("siteCode") or "")
    label = LABELS.get(site_code, site_code)
    product_code = str(account_payload.get("code") or "")
    account = _account(site_code)
    if not account:
        return {"site": label, "siteCode": site_code, "success": False, "productCode": product_code, "error": "온채널 계정 설정이 없습니다."}
    work_dir = Path(tempfile.mkdtemp(prefix=f"onchannel-register-{site_code}-", dir=config.DOWNLOAD_DIR))
    dialogs: list[str] = []
    try:
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=config.HEADLESS)
            context = await browser.new_context()
            page = await context.new_page()

            async def accept_dialog(dialog) -> None:
                dialogs.append(dialog.message)
                await dialog.accept()

            page.on("dialog", lambda dialog: asyncio.create_task(accept_dialog(dialog)))
            try:
                await _login(page, account)
                if await _registered_product_exists(page, product_code):
                    return {"site": label, "siteCode": site_code, "success": True, "alreadyRegistered": True, "productCode": product_code, "message": f"이미 등록된 상품입니다: {product_code}"}
                if await _draft_exists(page, product_code):
                    return await _verified_draft_result(page, request, account_payload, already=True)
                image_paths = await asyncio.to_thread(_download_images, account_payload, work_dir)
                await _fill_basic_form(page, request, account_payload, image_paths)
                await _set_options(page, request, account_payload)
                if preview:
                    return {"site": label, "siteCode": site_code, "success": True, "preview": True, "productCode": product_code, "message": "온채널 필수값 자동입력 검증 완료(임시저장 전 중단)"}

                # The basic-info editor is hidden on the options tab. Its content
                # was already committed above; opening Source here times out.
                await page.locator(".btn-temp-save:visible").last.click(no_wait_after=True)
                await page.wait_for_timeout(2200)
                if await _draft_exists(page, product_code):
                    return await _verified_draft_result(page, request, account_payload)
                relevant_dialogs = [message for message in dialogs if "상세페이지에 표시" not in message]
                raise RuntimeError(" / ".join(relevant_dialogs[-3:]) or "임시저장 후 등록중 목록에서 상품코드를 찾지 못했습니다.")
            finally:
                await browser.close()
    except Exception as exc:
        relevant_dialogs = [message for message in dialogs if "상세페이지에 표시" not in message]
        message = str(exc)
        dialog_text = " / ".join(relevant_dialogs[-5:])
        if dialog_text and dialog_text not in message:
            message = f"{message} / 사이트 안내: {dialog_text}"
        return {"site": label, "siteCode": site_code, "success": False, "productCode": product_code, "error": message[:1000]}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
