from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.onchannel import ACCOUNTS, dismiss_popups


LOGIN_URL = "https://www.onch3.co.kr/login/login_web.php"
REGISTER_LIST_URL = "https://www.onch3.co.kr/pending_products_management.php"
REGISTER_URL = "https://www.onch3.co.kr/regist_pending_products.php"
MANAGEMENT_URL = "https://www.onch3.co.kr/products_management.php"
LABELS = {"onch3": "온채널", "Fonch3": "F온채널"}


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
    return product_code.casefold() in (await page.locator("body").inner_text()).casefold()


async def _draft_exists(page: Page, product_code: str) -> bool:
    await _goto(page, f"{REGISTER_LIST_URL}?status=N&regSec=N")
    return product_code.casefold() in (await page.locator("body").inner_text()).casefold()


def _download_images(account: dict[str, Any], target_dir: Path) -> list[Path]:
    items = account.get("galleryImages") or [account["mainImage"], *account.get("additionalImages", [])]
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
    await page.locator("#editor").evaluate(
        """(element, value) => {
          element.value = value;
          element.dispatchEvent(new Event('input', {bubbles:true}));
          element.dispatchEvent(new Event('change', {bubbles:true}));
          if (window.CKEDITOR?.instances?.editor) window.CKEDITOR.instances.editor.setData(value);
          if (window.editor?.setData) window.editor.setData(value);
        }""",
        html,
    )


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
    await page.get_by_role("button", name="가격/옵션 정보 입력").click(no_wait_after=True)
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
        image_paths = _download_images(account_payload, work_dir)
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
                    return {"site": label, "siteCode": site_code, "success": True, "alreadyDraft": True, "draftSaved": True, "productCode": product_code, "message": f"이미 임시저장된 상품입니다: {product_code}"}
                await _fill_basic_form(page, request, account_payload, image_paths)
                await _set_options(page, request, account_payload)
                if preview:
                    return {"site": label, "siteCode": site_code, "success": True, "preview": True, "productCode": product_code, "message": "온채널 필수값 자동입력 검증 완료(임시저장 전 중단)"}

                await _set_editor_html(page, str(request.get("detailHtml") or ""))
                await page.locator(".btn-temp-save").last.click(no_wait_after=True)
                await page.wait_for_timeout(2200)
                if await _draft_exists(page, product_code):
                    return {"site": label, "siteCode": site_code, "success": True, "draftSaved": True, "productCode": product_code, "message": f"임시저장 완료: {product_code}"}
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
