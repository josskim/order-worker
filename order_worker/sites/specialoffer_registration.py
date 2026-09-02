from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.specialoffer_status import _click_visible_confirm, _login


SITE = "스페셜오퍼"
SITE_CODE = "specialoffer"
REGISTER_URL = "https://specialoffer.kr/mypage/page.php?code=seller_goods_form"
MANAGEMENT_URL = "https://specialoffer.kr/mypage/page.php?code=seller_goods_list"


async def _goto(page: Page, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(500)


async def _select_text(page: Page, selector: str, text: str) -> None:
    select = page.locator(selector).first
    options = await select.locator("option").evaluate_all(
        "els=>els.map(o=>({value:o.value,text:(o.textContent||'').replace(/\\s+/g,' ').trim()}))"
    )
    match = next((item for item in options if item["text"] == text), None)
    if match is None:
        raise RuntimeError(f"{SITE} 선택값을 찾지 못했습니다: {text}")
    await select.select_option(str(match["value"]))
    await page.wait_for_timeout(350)


async def _already_registered(page: Page, product_code: str) -> bool:
    await _goto(page, MANAGEMENT_URL)
    advanced = page.locator('input[type="button"][onclick*="search_date"]:visible').last
    if await advanced.count():
        await advanced.click()
    await page.locator('select[name="sfl"]').select_option("gname")
    await page.locator('input[name="stx"]').fill(product_code)
    search_form = page.locator('input[name="stx"]').locator("xpath=ancestor::form[1]")
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
        await search_form.locator('input[type="submit"]').click(no_wait_after=True)
    rows = page.locator("tbody tr").filter(has_text=product_code)
    for index in range(await rows.count()):
        if product_code.casefold() in (await rows.nth(index).inner_text()).casefold():
            return True
    return False


def _download_images(account: dict[str, Any], target_dir: Path) -> list[Path]:
    items = account.get("galleryImages") or [account["mainImage"], *account.get("additionalImages", [])]
    paths: list[Path] = []
    for index, item in enumerate(items[:6]):
        file_name = Path(str(item.get("fileName") or f"image-{index + 1}.jpg")).name
        target = target_dir / f"{index + 1:02d}-{file_name}"
        response = requests.get(str(item["url"]), timeout=45)
        response.raise_for_status()
        target.write_bytes(response.content)
        paths.append(target)
    if not paths:
        raise RuntimeError(f"{SITE}에 등록할 상품이미지가 없습니다.")
    return paths


async def _select_category(page: Page, category_path: list[str]) -> None:
    requested = [value for value in category_path if value]
    if requested[:2] == ["패션의류", "여성의류"]:
        requested = requested[1:]
    if requested and requested[-1] == "롱스커트":
        requested[-1] = "롱 스커트"
    for selector, label in zip(["#sel_ca1", "#sel_ca2", "#sel_ca3", "#sel_ca4", "#sel_ca5"], requested):
        await _select_text(page, selector, label)
    await page.get_by_role("button", name="카테고리 추가", exact=True).click()
    selected = [text.strip() for text in await page.locator("#sel_ca_id option").all_text_contents()]
    if not selected or not all(label in selected[-1] for label in requested):
        raise RuntimeError(f"{SITE} 카테고리가 추가되지 않았습니다: {' > '.join(selected)}")


async def _set_options(page: Page, colors: list[str], sizes: list[str]) -> None:
    if not colors and not sizes:
        return
    if colors:
        await page.locator("#opt1_subject").fill("색상")
        await page.locator("#opt1").fill(",".join(colors))
    if sizes:
        target = 2 if colors else 1
        await page.locator(f"#opt{target}_subject").fill("사이즈")
        await page.locator(f"#opt{target}").fill(",".join(sizes))
    await page.locator("#option_table_create").click()
    await page.wait_for_timeout(350)
    option_ids = page.locator('#sit_option_frm input[name="opt_id[]"]')
    expected = max(1, len(colors)) * max(1, len(sizes))
    if await option_ids.count() != expected:
        raise RuntimeError(f"{SITE} 옵션 조합이 생성되지 않았습니다. (예상 {expected}, 실제 {await option_ids.count()})")


async def _set_detail_html(page: Page, html: str) -> None:
    if not html.strip():
        raise RuntimeError(f"{SITE} 상품상세 HTML이 비어 있습니다.")
    await page.wait_for_function(
        "() => window.oEditors && window.oEditors.getById && window.oEditors.getById.memo",
        timeout=30000,
    )
    editor_frame = next((frame for frame in page.frames if "SmartEditor2Skin" in frame.url), None)
    if editor_frame is None:
        raise RuntimeError(f"{SITE} 상품상세 HTML 편집기를 찾지 못했습니다.")
    html_button = editor_frame.locator("button.se2_to_html")
    await html_button.wait_for(state="visible", timeout=10000)
    await html_button.click()
    source = editor_frame.locator("textarea.se2_input_htmlsrc")
    await source.wait_for(state="visible", timeout=5000)
    await source.fill(html)
    if await source.input_value() != html:
        raise RuntimeError(f"{SITE} HTML 편집기에 상품상세 이미지 URL이 반영되지 않았습니다.")
    await page.evaluate("() => window.oEditors.getById.memo.exec('UPDATE_CONTENTS_FIELD', [])")


async def _verify_form_values(page: Page, request: dict[str, Any], account: dict[str, Any], image_count: int) -> None:
    specialoffer = request.get("specialoffer") or {}
    expected = {
        "#normal_price": int(specialoffer.get("consumerPrice") or 0),
        "#supply_price": int(account["supplyPrice"]),
        'input[name="sc_amt"]': int(specialoffer.get("shippingFee") or 3000),
    }
    for selector, wanted in expected.items():
        actual = int((await page.locator(selector).input_value()).replace(",", "") or 0)
        if actual != wanted:
            raise RuntimeError(f"{SITE} 금액 검증 실패: {selector} 예상 {wanted:,}원, 실제 {actual:,}원")
    attached = 0
    for index in range(image_count):
        if await page.locator(f"#item_file_fld_{index + 1}").input_value():
            attached += 1
    if attached != image_count:
        raise RuntimeError(f"{SITE} 상품이미지 첨부 검증 실패: 예상 {image_count}장, 실제 {attached}장")


async def _fill_form(
    page: Page,
    request: dict[str, Any],
    account: dict[str, Any],
    image_paths: list[Path],
) -> None:
    await _goto(page, REGISTER_URL)
    if await page.locator('#fregform input[name="seller_gcode"]').count() == 0:
        raise RuntimeError(f"{SITE} 상품등록 화면에 접근하지 못했습니다: {page.url}")

    specialoffer = request.get("specialoffer") or {}
    category_path = specialoffer.get("categoryPath") or ["여성의류", "스커트", "롱 스커트"]
    await _select_category(page, [str(value) for value in category_path])
    await page.locator('input[name="seller_gcode"]').fill(str(account["code"]))
    await page.locator('input[name="gname"]').fill(str(account["productName"]))
    await page.locator('input[name="keywords"]').fill(str(request.get("keywords") or ""))
    await page.locator('input[name="brand_nm"]').fill(str(specialoffer.get("brand") or "프라하"))
    await page.locator('input[name="model"]').fill(str(account["modelName"]))
    await page.locator('input[name="maker"]').fill(str(account.get("manufacturer") or "프라하"))
    await _select_text(page, 'select[name="origin1"]', "해외")
    await _select_text(page, 'select[name="origin2"]', "아시아")
    await _select_text(page, 'select[name="origin3"]', "중국")
    cutoff = str(specialoffer.get("orderCutoff") or "14:00").split(":", 1)
    cutoff_fields = page.locator('select[name="end_at[]"]')
    await cutoff_fields.nth(0).select_option(cutoff[0])
    await cutoff_fields.nth(1).select_option(cutoff[1] if len(cutoff) > 1 else "00")

    await _set_options(
        page,
        [str(value) for value in request.get("colors", []) if str(value).strip()],
        [str(value) for value in request.get("sizes", []) if str(value).strip()],
    )
    await page.locator("#supply_price").fill(str(account["supplyPrice"]))
    # 공급가격 입력 이벤트가 소비자가를 자동 재계산하므로 소비자가를 마지막에 확정한다.
    await page.locator("#normal_price").fill(str(specialoffer.get("consumerPrice") or 0))
    await _select_text(page, 'select[name="sc_type"]', "유료배송")
    await _select_text(page, 'select[name="sc_method"]', "선결제")
    await page.locator('input[name="sc_amt"]').fill(str(specialoffer.get("shippingFee") or 3000))
    await page.locator('input[name="zone_msg"]').fill(
        str(specialoffer.get("shippingExtraDescription") or "제주 3,000,울릉도 6,000,도서산간 9,000 추가입니다.")
    )
    for index, image_path in enumerate(image_paths):
        await page.locator(f"#item_file_fld_{index + 1}").set_input_files(str(image_path))
    await _set_detail_html(page, str(request.get("detailHtml") or ""))
    await _verify_form_values(page, request, account, len(image_paths))


async def run_account(request: dict[str, Any], account_payload: dict[str, Any], preview: bool = False) -> dict[str, Any]:
    site_code = str(account_payload.get("siteCode") or "")
    product_code = str(account_payload.get("code") or "")
    work_dir = Path(tempfile.mkdtemp(prefix="specialoffer-register-", dir=config.DOWNLOAD_DIR))
    dialogs: list[str] = []
    try:
        image_paths = _download_images(account_payload, work_dir)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=config.HEADLESS)
            context = await browser.new_context(viewport={"width": 1800, "height": 1200})
            page = await context.new_page()

            async def accept_dialog(dialog) -> None:
                dialogs.append(dialog.message)
                await dialog.accept()

            page.on("dialog", lambda dialog: asyncio.create_task(accept_dialog(dialog)))
            try:
                await _login(page)
                if await _already_registered(page, product_code):
                    return {"site": SITE, "siteCode": site_code, "success": True, "alreadyRegistered": True, "productCode": product_code, "message": f"이미 등록된 상품입니다: {product_code}"}
                await _fill_form(page, request, account_payload, image_paths)
                if preview:
                    return {"site": SITE, "siteCode": site_code, "success": True, "preview": True, "productCode": product_code, "message": "스페셜오퍼 필수값 자동입력 검증 완료(저장 전 중단)"}

                await page.get_by_role("button", name="저장", exact=True).click(no_wait_after=True)
                await _click_visible_confirm(page, timeout=5000)
                await page.wait_for_timeout(2200)
                if await _already_registered(page, product_code):
                    return {"site": SITE, "siteCode": site_code, "success": True, "productCode": product_code, "message": f"상품등록 완료: {product_code}"}
                raise RuntimeError(f"{SITE} 저장 후 전체상품 관리에서 업체상품코드를 찾지 못했습니다.")
            finally:
                await browser.close()
    except Exception as exc:
        message = str(exc)
        dialog_text = " / ".join(dialogs[-6:])
        if dialog_text and dialog_text not in message:
            message = f"{message} / 사이트 안내: {dialog_text}"
        return {"site": SITE, "siteCode": site_code, "success": False, "productCode": product_code, "error": message[:1600]}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
