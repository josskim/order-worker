from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.ownerclan import ACCOUNTS


LOGIN_URL = "https://ownerclan.com/vender/login.php"
REGISTER_URL = "https://ownerclan.com/vender/product_register.php"
MANAGEMENT_URL = "https://ownerclan.com/vender/product_myprd.php"
LABELS = {"ownerclan": "오너클랜", "Fownerclan": "F오너클랜"}


def _account(account_code: str):
    return next((account for account in ACCOUNTS if account[0] == account_code), None)


async def _stop_loading(page: Page) -> None:
    try:
        await page.evaluate("window.stop()")
    except Exception:
        pass


async def _login(page: Page, account) -> None:
    _, user_id, password, label = account
    print(f"PROGRESS: [{label}] 상품등록 로그인 중...")
    page.set_default_timeout(10000)
    page.set_default_navigation_timeout(10000)
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await page.fill('input[name="id"]', user_id)
    await page.fill('input[name="passwd"]', password)
    try:
        await page.click('input[type="submit"]')
    except Exception:
        # 오너클랜 로그인 완료 화면에 장시간 연결되는 보조 리소스가 있어
        # 탐색 타임아웃이 나더라도 인증 쿠키는 이미 발급되어 있다.
        pass
    await page.wait_for_timeout(1000)
    await _stop_loading(page)


async def _goto(page: Page, url: str) -> None:
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(1200)
    await _stop_loading(page)


async def _already_registered(page: Page, product_code: str) -> bool:
    await _goto(page, MANAGEMENT_URL)
    search_type = page.locator('select[name="s_check"]:visible').first
    if await search_type.count() == 0:
        raise RuntimeError(f"오너클랜 상품관리 화면에 접근하지 못했습니다: {page.url}")
    await search_type.select_option("model")
    await page.locator('input[name="search"]:visible').first.fill(product_code)
    await page.locator('button[onclick*="SearchPrd"]:visible').first.click()
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass
    await page.wait_for_timeout(600)
    rows = page.locator('a[href*="GoPrdinfo"]')
    count = await rows.count()
    if count == 0:
        return False
    texts = [await rows.nth(index).locator("xpath=ancestor::tr[1]").inner_text() for index in range(count)]
    return any(product_code.casefold() in text.casefold() for text in texts)


async def _select_text(page: Page, selector: str, label: str) -> None:
    select = page.locator(selector).first
    await select.wait_for(state="visible")
    options = await select.locator("option").evaluate_all(
        "els => els.map(o => ({value:o.value, text:(o.textContent || '').replace('☞','').trim()}))"
    )
    match = next((option for option in options if option["text"] == label), None)
    if not match:
        raise RuntimeError(f"오너클랜 선택값을 찾지 못했습니다: {label}")
    await select.select_option(str(match["value"]))
    await page.wait_for_timeout(350)


async def _select_category(page: Page, category_path: list[str]) -> None:
    selectors = ['select[name="code1"]', 'select[name="code2"]', 'select[name="code3"]', 'select[name="code4"]']
    for selector, label in zip(selectors, category_path):
        if label:
            await _select_text(page, selector, label)
    # 사용자 규칙: 세분류가 실제로 제공되면 첫 번째 값을 반드시 선택한다.
    detail_select = page.locator('select[name="code4"]').first
    if await detail_select.count():
        options = await detail_select.locator("option").evaluate_all("els => els.map(o => ({value:o.value,text:(o.textContent||'').trim()}))")
        first_value = next((str(item["value"]) for item in options if str(item["value"]).strip()), "")
        if first_value and not await detail_select.input_value():
            await detail_select.select_option(first_value)


def _download_images(account: dict[str, Any], target_dir: Path) -> tuple[Path, list[Path]]:
    items = [account["mainImage"], *account.get("additionalImages", [])]
    paths: list[Path] = []
    for index, item in enumerate(items):
        file_name = Path(str(item.get("fileName") or f"image-{index}.jpg")).name
        target = target_dir / f"{index:02d}-{file_name}"
        response = requests.get(str(item["url"]), timeout=45)
        response.raise_for_status()
        target.write_bytes(response.content)
        paths.append(target)
    return paths[0], paths[1:]


async def _set_options(page: Page, colors: list[str], sizes: list[str]) -> None:
    if not colors and not sizes:
        return
    await page.locator("#useOption1").check()
    async with page.expect_popup(timeout=10000) as popup_info:
        await page.locator("#btn_option").click()
    popup = await popup_info.value
    await popup.wait_for_load_state("domcontentloaded")
    option_rows = []
    if colors:
        option_rows.append(("색상", colors))
    if sizes:
        option_rows.append(("사이즈", sizes))
    for index, (name, values) in enumerate(option_rows):
        if index:
            await popup.get_by_role("button", name="+").last.click()
        await popup.locator(f'input[name="optionname{index}"]').fill(name)
        await popup.locator(f'input[name="optionalvalue{index}"]').fill(",".join(values))
    await popup.get_by_role("button", name="옵션 구성 ↓").click()
    await popup.wait_for_timeout(400)
    await popup.get_by_role("button", name="옵션 설정 완료").click()
    await page.wait_for_timeout(400)
    await page.bring_to_front()
    if not await page.locator("#optionsData").input_value():
        raise RuntimeError("오너클랜 옵션 조합이 본문에 반영되지 않았습니다.")


async def _fill_form(page: Page, request: dict[str, Any], account: dict[str, Any], image_dir: Path) -> None:
    await _goto(page, REGISTER_URL)
    if await page.locator('input[name="productname"]').count() == 0:
        raise RuntimeError(f"오너클랜 상품등록 화면에 접근하지 못했습니다: {page.url}")
    await _select_category(page, [str(value) for value in request.get("categoryPath", [])])
    await page.fill('input[name="productname"]', str(account["productName"]))
    await page.fill('input[name="productname_deli"]', str(account["invoiceProductName"]))
    await page.fill('input[name="ompkeyword"]', str(request.get("keywords") or ""))
    await page.locator("#origin_nation2").check()
    await _select_text(page, "#foreign_continent", "아시아")
    await _select_text(page, "#foreign_nation", "중국")
    await page.fill("#production", str(account["manufacturer"]))
    await page.fill('input[name="model"]', str(account["modelName"]))
    await page.fill("#sellprice", str(request["salePrice"]))
    await page.locator("#tax_mode1").check()
    await _set_options(page, [str(value) for value in request.get("colors", [])], [str(value) for value in request.get("sizes", [])])

    main_path, additional_paths = _download_images(account, image_dir)
    await page.locator("#userfile").set_input_files(str(main_path))
    if additional_paths:
        await page.locator("#up_files").set_input_files([str(path) for path in additional_paths])
    await page.locator('input[name="productCondition"][value="new"]').check()
    await page.locator(f'input[name="sell_minors"][value="{"Y" if request.get("minorSalesAllowed") else "N"}"]').check()
    await page.locator('input[name="medicalAttr"][value="N"]').check()
    await page.locator('input[name="hfoodAttr"][value="N"]').check()
    detail_html = str(request.get("detailHtml") or "")
    await page.locator("#content").evaluate("(element, html) => { element.value = html; }", detail_html)
    await page.evaluate(
        "html => { if (window.oEditors2?.getById?.content) window.oEditors2.getById.content.exec('SET_IR', [html]); }",
        detail_html,
    )
    await page.locator("#delimode_S").check()
    await page.fill("#deliprice_val", str(request.get("shipping", {}).get("fee", 3000)))
    await page.locator("#idx_returncheck1").check()
    await page.locator("#returnStatus2").check()
    await page.fill("#max1boxquan", str(request.get("shipping", {}).get("bundleQuantity", 100)))
    await page.locator("#certify_mode2").check()
    notice = str(request.get("noticeCategory") or "의류")
    notice_label = "패션잡화(모자/벨트/액세서리)" if notice == "패션잡화" else notice
    await _select_text(page, "#nfcategory", notice_label)
    await page.locator("#all_nf").check()


async def run_account(request: dict[str, Any], account_payload: dict[str, Any], preview: bool = False) -> dict[str, Any]:
    site_code = str(account_payload.get("siteCode") or "")
    label = LABELS.get(site_code, site_code)
    product_code = str(account_payload.get("code") or "")
    account = _account(site_code)
    if not account:
        return {"site": label, "siteCode": site_code, "success": False, "productCode": product_code, "error": "오너클랜 계정 설정이 없습니다."}
    work_dir = Path(tempfile.mkdtemp(prefix=f"ownerclan-register-{site_code}-", dir=config.DOWNLOAD_DIR))
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
                if await _already_registered(page, product_code):
                    return {"site": label, "siteCode": site_code, "success": True, "alreadyRegistered": True, "productCode": product_code, "message": f"이미 등록된 상품입니다: {product_code}"}
                await _fill_form(page, request, account_payload, work_dir)
                if preview:
                    return {"site": label, "siteCode": site_code, "success": True, "preview": True, "productCode": product_code, "message": "필수값 자동입력 검증 완료(최종 등록 전 중단)"}

                await page.locator('a[href*="formSubmit"]').click()
                await page.wait_for_timeout(400)
                # 최초 등록 시 지적재산권 안내가 표시된다. '일주일 동안 보이지
                # 않기' 체크가 이 사이트의 실제 확인 동작이며, 체크 즉시 같은
                # formSubmit을 다시 실행한다.
                if await page.locator("#submitFont").is_visible():
                    try:
                        await page.locator("#smtChk").check(timeout=5000)
                    except Exception:
                        # 체크 onclick 안에서 동기 등록 후 페이지를 즉시 다시
                        # 불러오므로 Playwright가 기존 체크박스를 재확인하다가
                        # 타임아웃될 수 있다. 아래 모델명 조회가 최종 판정이다.
                        pass
                await page.wait_for_timeout(3000)
                await _stop_loading(page)
                if await _already_registered(page, product_code):
                    return {"site": label, "siteCode": site_code, "success": True, "productCode": product_code, "message": f"상품등록 완료: {product_code}"}
                dialog_text = " / ".join(dialogs[-3:])
                raise RuntimeError(dialog_text or "등록 후 상품관리에서 모델명을 찾지 못했습니다.")
            finally:
                await browser.close()
    except Exception as exc:
        dialog_text = " / ".join(dialogs[-5:])
        message = str(exc)
        if dialog_text and dialog_text not in message:
            message = f"{message} / 사이트 안내: {dialog_text}"
        return {"site": label, "siteCode": site_code, "success": False, "productCode": product_code, "error": message[:1000]}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def run(request: dict[str, Any], preview: bool = False, on_progress=None) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for account in request.get("accounts", []):
        site_code = str(account.get("siteCode") or "")
        if on_progress:
            on_progress(site_code, results.copy())
        results.append(await run_account(request, account, preview=preview))
        if on_progress:
            on_progress(None, results.copy())
    return results
