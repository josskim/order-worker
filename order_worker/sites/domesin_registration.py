from __future__ import annotations

import asyncio
import shutil
import tempfile
from itertools import product
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.domesin import PASSWORD, USER_ID


SITE = "도매의신"
SITE_CODE = "domesin"
LOGIN_URL = "https://www.domesin.com/scm/login.html"
REGISTER_URL = "https://www.domesin.com/scm/M_item/item_form.html"
MANAGEMENT_URL = "https://www.domesin.com/scm/M_item/item_list.html"


async def _login(page: Page) -> None:
    page.set_default_timeout(12000)
    page.set_default_navigation_timeout(30000)
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await page.fill('body > div > form > input[type="text"]:nth-child(4)', USER_ID)
    await page.fill('body > div > form > input[type="password"]:nth-child(5)', PASSWORD)
    await page.click("body > div > form > button.login-btn", no_wait_after=True)
    await page.wait_for_url(lambda url: "/scm/login.html" not in url, wait_until="domcontentloaded", timeout=30000)


async def _goto(page: Page, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(450)


async def _select_text(page: Page, selector: str, label: str) -> None:
    select = page.locator(selector).first
    options = await select.locator("option").evaluate_all(
        "els=>els.map(o=>({value:o.value,text:(o.textContent||'').replace(/\\s+/g,' ').trim()}))"
    )
    match = next((item for item in options if item["text"] == label), None)
    if match is None:
        raise RuntimeError(f"{SITE} 선택값을 찾지 못했습니다: {label}")
    await select.select_option(str(match["value"]))
    await page.wait_for_timeout(300)


async def _already_registered(page: Page, product_code: str) -> bool:
    await _goto(page, MANAGEMENT_URL)
    await page.locator("#q_type").select_option("iname")
    await page.locator("#q").fill(product_code)
    search_form = page.locator("#q").locator("xpath=ancestor::form[1]")
    async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
        await search_form.locator('input[type="submit"]').click(no_wait_after=True)
    codes = page.locator('input[name^="vender_code_"]')
    for index in range(await codes.count()):
        if (await codes.nth(index).input_value()).strip().casefold() == product_code.strip().casefold():
            return True
    return False


def _download_main_image(account: dict[str, Any], target_dir: Path) -> Path:
    image = account["mainImage"]
    file_name = Path(str(image.get("fileName") or "main.jpg")).name
    target = target_dir / file_name
    response = requests.get(str(image["url"]), timeout=45)
    response.raise_for_status()
    target.write_bytes(response.content)
    return target


async def _select_category(page: Page, category_path: list[str]) -> None:
    requested = [value for value in category_path if value]
    selectors = ['select[name="cate1"]', 'select[name="cate2"]', 'select[name="cate3"]', 'select[name="cate4"]']
    for selector, label in zip(selectors, requested):
        await _select_text(page, selector, label)
    category_id = await page.locator("#cid").input_value()
    selected_path = await page.locator("#path_txt").input_value()
    if not category_id or not requested or requested[-1] not in selected_path:
        raise RuntimeError(f"{SITE} 카테고리가 선택되지 않았습니다: {selected_path or '선택 없음'}")


async def _set_options(page: Page, colors: list[str], sizes: list[str]) -> None:
    combinations = list(product(colors or [""], sizes or [""]))
    combinations = [(color, size) for color, size in combinations if color or size]
    if not combinations:
        return
    await page.locator('input[name="list_option_use"][value="1"]').check()
    use_two_levels = bool(colors and sizes)
    if use_two_levels:
        await page.locator("#op_deep").check()
    await page.locator("#op_t1").fill("색상" if colors else "사이즈")
    if use_two_levels:
        await page.locator("#op_t2").fill("사이즈")
    for _ in range(1, len(combinations)):
        await page.locator('input[onclick="add_option();"]').click()
    first_values = page.locator('input[name="op_n1[]"]')
    second_values = page.locator('input[name="op_n2[]"]')
    for index, (color, size) in enumerate(combinations):
        await first_values.nth(index).fill(color if colors else size)
        if use_two_levels:
            await second_values.nth(index).fill(size)
    if await first_values.count() != len(combinations):
        raise RuntimeError(f"{SITE} 옵션 조합 생성 실패: 예상 {len(combinations)}, 실제 {await first_values.count()}")


async def _set_detail_html(page: Page, html: str) -> None:
    if not html.strip():
        raise RuntimeError(f"{SITE} 상품상세 HTML이 비어 있습니다.")
    await page.wait_for_function("() => window.CKEDITOR?.instances?.i_content", timeout=20000)
    source_button = page.locator(".cke_button__source, #cke_30").first
    await source_button.wait_for(state="visible", timeout=10000)
    await source_button.click()
    source = page.locator("textarea.cke_source:visible")
    await source.wait_for(state="visible", timeout=5000)
    await source.fill(html)
    if await source.input_value() != html:
        raise RuntimeError(f"{SITE} 소스 편집기에 상품상세 이미지 HTML이 반영되지 않았습니다.")
    await page.evaluate("() => window.CKEDITOR.instances.i_content.updateElement()")


async def _verify_form(page: Page, request: dict[str, Any], account: dict[str, Any]) -> None:
    domesin = request.get("domesin") or {}
    expected = {
        'input[name="cost"]': int(account["supplyPrice"]),
        'input[name="amount_g"]': int(domesin.get("consumerPrice") or 0),
        "#delivery_amount": int(domesin.get("shippingFee") or 3000),
        "#delivery_qty": int(domesin.get("bundleQuantity") or 100),
        "#r_delivery_amount": int(domesin.get("returnShippingFee") or 3000),
    }
    for selector, wanted in expected.items():
        actual = int((await page.locator(selector).input_value()).replace(",", "") or 0)
        if actual != wanted:
            raise RuntimeError(f"{SITE} 입력값 검증 실패: {selector} 예상 {wanted:,}, 실제 {actual:,}")
    if not await page.locator("#photo").input_value():
        raise RuntimeError(f"{SITE} 상품 대표이미지가 첨부되지 않았습니다.")


async def _fill_form(page: Page, request: dict[str, Any], account: dict[str, Any], image_path: Path) -> None:
    await _goto(page, REGISTER_URL)
    if await page.locator('input[name="iname"]').count() == 0:
        raise RuntimeError(f"{SITE} 상품등록 화면에 접근하지 못했습니다: {page.url}")
    domesin = request.get("domesin") or {}
    category_path = [str(value) for value in domesin.get("categoryPath") or request.get("categoryPath", [])]
    await _select_category(page, category_path)
    # 도매의신은 상품명에 밑줄 문자를 허용하지 않는다.
    product_name = str(account["productName"]).replace("_", " ")
    await page.locator('input[name="iname"]').fill(product_name)
    await page.locator('input[name="vender_code"]').fill(str(account["code"]))
    await _select_text(page, 'select[name="c1"]', "해외")
    await _select_text(page, 'select[name="c2"]', "아시아")
    await _select_text(page, 'select[name="c3"]', "중국")
    await page.locator('input[name="ibrand"]').fill(str(domesin.get("brand") or "프라하"))
    await page.locator('input[name="icompany"]').fill(str(account.get("manufacturer") or "프라하"))
    await page.locator('input[name="imodel"]').fill(str(account["modelName"]))
    await page.locator('input[name="keyword"]').fill(str(request.get("keywords") or ""))
    await page.locator('input[name="cost"]').fill(str(account["supplyPrice"]))
    await page.locator('input[name="amount_g"]').fill(str(domesin.get("consumerPrice") or 0))
    await _select_text(page, 'select[name="delivery_type"]', str(domesin.get("shippingPolicy") or "기본배송"))
    await page.locator("#delivery_amount").fill(str(domesin.get("shippingFee") or 3000))
    # 기본배송 선택 시 화면은 묶음배송수량을 readonly로 만들지만 폼 필드는
    # 서버에 전송된다. 사용자가 지정한 100을 값으로 직접 반영한다.
    await page.locator("#delivery_qty").evaluate(
        "(element, value) => { element.value = value; }",
        str(domesin.get("bundleQuantity") or 100),
    )
    await page.locator("#r_delivery_amount").fill(str(domesin.get("returnShippingFee") or 3000))
    await _set_options(
        page,
        [str(value) for value in request.get("colors", []) if str(value).strip()],
        [str(value) for value in request.get("sizes", []) if str(value).strip()],
    )
    await page.locator("#photo").set_input_files(str(image_path))
    await _select_text(page, "#cert_type", "인증대상아님")
    await _set_detail_html(page, str(request.get("detailHtml") or ""))
    notice = str(request.get("noticeCategory") or "의류")
    notice_label = "- 패션잡화(모자/벨트/액세서리)" if notice == "패션잡화" else f"- {notice}"
    await _select_text(page, "#gosi_g", notice_label)
    await page.locator("#gosi_ack").check()
    await _verify_form(page, request, account)


async def run_account(request: dict[str, Any], account_payload: dict[str, Any], preview: bool = False) -> dict[str, Any]:
    product_code = str(account_payload.get("code") or "")
    work_dir = Path(tempfile.mkdtemp(prefix="domesin-register-", dir=config.DOWNLOAD_DIR))
    dialogs: list[str] = []
    try:
        image_path = _download_main_image(account_payload, work_dir)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=config.HEADLESS)
            page = await browser.new_page(viewport={"width": 1800, "height": 1400})

            async def accept_dialog(dialog) -> None:
                dialogs.append(dialog.message)
                await dialog.accept()

            page.on("dialog", lambda dialog: asyncio.create_task(accept_dialog(dialog)))
            try:
                await _login(page)
                if await _already_registered(page, product_code):
                    return {"site": SITE, "siteCode": SITE_CODE, "success": True, "alreadyRegistered": True, "productCode": product_code, "message": f"이미 등록된 상품입니다: {product_code}"}
                await _fill_form(page, request, account_payload, image_path)
                if preview:
                    return {"site": SITE, "siteCode": SITE_CODE, "success": True, "preview": True, "productCode": product_code, "message": "도매의신 필수값 자동입력 검증 완료(저장 전 중단)"}
                save = page.locator('input[type="submit"][value="상품정보 저장하기"]')
                async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
                    await save.click(no_wait_after=True)
                await page.wait_for_timeout(1400)
                if await _already_registered(page, product_code):
                    return {"site": SITE, "siteCode": SITE_CODE, "success": True, "productCode": product_code, "message": f"상품등록 완료: {product_code}"}
                raise RuntimeError(f"{SITE} 저장 후 상품관리에서 업체상품코드를 찾지 못했습니다.")
            finally:
                await browser.close()
    except Exception as exc:
        message = str(exc)
        dialog_text = " / ".join(dialogs[-6:])
        if dialog_text and dialog_text not in message:
            message = f"{message} / 사이트 안내: {dialog_text}"
        return {"site": SITE, "siteCode": SITE_CODE, "success": False, "productCode": product_code, "error": message[:1600]}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
