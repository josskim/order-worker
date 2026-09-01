from __future__ import annotations

import asyncio
import re
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.domeggook import ACCOUNTS
from order_worker.sites.domeggook_status import _login


REGISTER_URL = "https://www.domeggook.com/sc/item/regFrm"
MANAGEMENT_URL = "https://www.domeggook.com/sc/item/lstAll"
LABELS = {"domeggook": "도매꾹", "Fdomeggook": "F도매꾹"}


def _account(account_code: str):
    return next((account for account in ACCOUNTS if account[0] == account_code), None)


async def _goto(page: Page, url: str) -> None:
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(700)


async def _already_registered(page: Page, product_code: str) -> bool:
    await _goto(page, MANAGEMENT_URL)
    search = page.locator('input[name="ttl"]')
    if await search.count() == 0:
        raise RuntimeError(f"도매꾹 상품관리 화면에 접근하지 못했습니다: {page.url}")
    await search.fill(product_code)
    await page.locator('input[type="submit"]').first.click()
    await page.wait_for_timeout(1500)
    cells = page.locator('td[data-column-name="code"]')
    values = [re.sub(r"\s+", "", await cells.nth(index).inner_text()) for index in range(await cells.count())]
    return re.sub(r"\s+", "", product_code).casefold() in [value.casefold() for value in values]


async def _select_text(page: Page, selector: str, text: str) -> None:
    select = page.locator(selector).first
    options = await select.locator("option").evaluate_all(
        "els=>els.map(o=>({value:o.value,text:(o.textContent||'').replace(/\\s+/g,' ').trim()}))"
    )
    match = next((item for item in options if item["text"] == text), None)
    if match is None:
        match = next((item for item in options if text in item["text"]), None)
    if match is None:
        raise RuntimeError(f"도매꾹 선택값을 찾지 못했습니다: {text}")
    await select.select_option(str(match["value"]))
    await page.wait_for_timeout(350)


async def _select_shipping_address(page: Page, selector: str, label: str) -> None:
    select = page.locator(selector).first
    options = await select.locator("option").evaluate_all(
        "els=>els.map(o=>({value:o.value,text:(o.textContent||'').replace(/\\s+/g,' ').trim()})).filter(o=>o.value)"
    )
    exact = next((item for item in options if item["text"] == label), None)
    if exact is not None:
        await select.select_option(str(exact["value"]))
        return
    # F계정은 같은 실주소를 '롯데택배'라는 이름으로 저장해 두었다. 이름이
    # 달라도 실제 주소가 남천로 31 프라하빌딩으로 검증될 때만 사용한다.
    if len(options) == 1:
        await select.select_option(str(options[0]["value"]))
        await page.wait_for_timeout(300)
        row_text = await select.locator("xpath=ancestor::tr[1]").inner_text()
        if "남천로 31" in row_text and "프라하빌딩" in row_text:
            return
    raise RuntimeError(f"도매꾹 출고/반품지 '{label}' 또는 동일 실주소를 찾지 못했습니다.")


async def _select_category(page: Page, category_path: list[str]) -> None:
    mapped = ["의류/언더웨어" if value == "패션의류" else value for value in category_path if value]
    for label in mapped:
        button = page.locator("button.lCategoryBtn", has_text=label)
        await button.first.wait_for(state="visible", timeout=10000)
        await button.first.click()
        await page.wait_for_timeout(450)
    category_id = await page.locator("#lItemCategoryInput").input_value()
    selected_text = await page.locator(".pCategorySelector .lCategoryName").inner_text()
    if not category_id or not mapped or mapped[-1] not in selected_text:
        raise RuntimeError(f"도매꾹 카테고리를 확인하지 못했습니다: {selected_text or '선택 없음'}")
    notice = page.locator("#lDialogSellReg:visible")
    if await notice.count():
        text = await notice.inner_text()
        if "안전확인대상 상품 판매 시 유의사항" not in text:
            raise RuntimeError(f"도매꾹 카테고리 선택 후 확인되지 않은 안내가 표시됐습니다: {text[:300]}")
        await notice.get_by_role("button", name="확인", exact=True).click()


def _download_main_image(account: dict[str, Any], target_dir: Path) -> Path:
    item = account["mainImage"]
    file_name = Path(str(item.get("fileName") or "main.jpg")).name
    target = target_dir / file_name
    response = requests.get(str(item["url"]), timeout=45)
    response.raise_for_status()
    target.write_bytes(response.content)
    return target


async def _keep_requested_category(page: Page) -> None:
    keep = page.get_by_role("button", name="유지하기", exact=True)
    try:
        await keep.wait_for(state="visible", timeout=10000)
        await keep.click()
        await page.locator("#lDialogSellReg").wait_for(state="hidden", timeout=5000)
    except Exception:
        pass


async def _set_detail_html(page: Page, html: str) -> None:
    async with page.expect_popup(timeout=12000) as popup_info:
        await page.locator("#lBtnWriteItemMemo").click()
    popup = await popup_info.value
    await popup.wait_for_load_state("domcontentloaded")
    popup.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
    for selector in ["#lChkDeli", "#lChkEvent", "#lChkOtherItem"]:
        checkbox = popup.locator(selector)
        if await checkbox.is_checked():
            await checkbox.uncheck()
    await popup.evaluate(
        """value => {
          const item = window.editorController?.data?.[0];
          if (!item?.editor?.setHtml) throw new Error('상품정보 편집기를 찾지 못했습니다.');
          item.editor.setHtml(value);
          item.hasContent = true;
        }""",
        html,
    )
    await popup.locator("#lBtnSubmit").click()
    if not popup.is_closed():
        await popup.wait_for_event("close", timeout=10000)
    await page.bring_to_front()
    await page.wait_for_timeout(400)
    allow = page.get_by_text("이미지 사용허용", exact=True)
    if await allow.count():
        await allow.first.click()


async def _set_prices(page: Page, price: int) -> None:
    await page.locator('input[name="market[]"][value="dome"]').check()
    await page.locator('input[name="market[]"][value="supply"]').check()
    await page.evaluate(
        """price => {
          module.itemAmtSectionTbl.updateData({idx:0,key:'start',val:'1'});
          module.itemAmtSectionTbl.updateData({idx:0,key:'amt',val:String(price)});
          module.itemSupplyAmtSectionTbl.updateData({idx:0,key:'start',val:'1'});
          module.itemSupplyAmtSectionTbl.updateData({idx:0,key:'amt',val:String(price)});
        }""",
        price,
    )
    if await page.locator("#lUnitQty").input_value() != "1" or await page.locator("#lAmt1").input_value() != str(price):
        raise RuntimeError("도매꾹 판매단가가 전송값에 반영되지 않았습니다.")
    if await page.locator("#lSupplyQty").input_value() != "1" or await page.locator("#lSupplyAmt").input_value() != str(price):
        raise RuntimeError("도매매 판매단가가 전송값에 반영되지 않았습니다.")


async def _set_options(page: Page, colors: list[str], sizes: list[str]) -> None:
    option_rows: list[tuple[str, list[str]]] = []
    if colors:
        option_rows.append(("색상", colors))
    if sizes:
        option_rows.append(("사이즈", sizes))
    if not option_rows:
        return
    await page.locator("#lItemOptUse").check()
    async with page.expect_popup(timeout=12000) as popup_info:
        await page.locator("#lBtnItemOpt").click()
    popup = await popup_info.value
    await popup.wait_for_load_state("domcontentloaded")
    await popup.locator("#selItemOpt").select_option(str(len(option_rows)))
    await popup.wait_for_timeout(250)
    name_fields = popup.locator('input[name="optName[]"]')
    value_fields = popup.locator('input[name="optValue[]"]')
    price_fields = popup.locator('input[name="optPrice[]"]')
    for index, (name, values) in enumerate(option_rows):
        await name_fields.nth(index).fill(name)
        await value_fields.nth(index).fill(",".join(values))
        await price_fields.nth(index).fill("0")
    await popup.locator('img[onclick="checkOptType()"]').click()
    await popup.wait_for_timeout(700)
    quantities = popup.locator('input[name="qty[]"]')
    if await quantities.count() == 0:
        raise RuntimeError("도매꾹 옵션 조합이 생성되지 않았습니다.")
    for index in range(await quantities.count()):
        await quantities.nth(index).fill("9999")
    await popup.locator('img[onclick*="endOptSet"]').last.click()
    if not popup.is_closed():
        await popup.wait_for_event("close", timeout=10000)
    await page.bring_to_front()
    if not await page.locator("#setOptInp").input_value():
        raise RuntimeError("도매꾹 옵션 설정이 본문에 반영되지 않았습니다.")


async def _set_shipping(page: Page, fee: int) -> None:
    await page.locator("#lItemPeriodDeli2").check()
    await page.locator('input[name="deliveryWho"][value="P"]').check()
    await page.evaluate(
        """fee => {
          module.deliSecTblDome.updateData({idx:0,key:'start',val:'1'});
          module.deliSecTblDome.updateData({idx:0,key:'amt',val:String(fee)});
          module.deliSecTblSupply.updateData({idx:0,key:'start',val:'1'});
          module.deliSecTblSupply.updateData({idx:0,key:'amt',val:String(fee)});
        }""",
        fee,
    )
    await page.locator('input[name="lDeliMergeEnable"][value="y"]').check()
    await _select_shipping_address(page, "#lDeliShippingArea", "프라하빌딩")
    await _select_shipping_address(page, "#lDeliAddrReturnSelect", "프라하빌딩")
    await page.locator("#lReturnAmtInput").fill(str(fee))
    await page.locator("#lReturnAmtInput").press("Tab")


async def _fill_form(page: Page, request: dict[str, Any], account: dict[str, Any], image_path: Path) -> None:
    await _goto(page, REGISTER_URL)
    if await page.locator('input[name="itemTitle"]').count() == 0:
        raise RuntimeError(f"도매꾹 상품등록 화면에 접근하지 못했습니다: {page.url}")
    await page.locator('input[name="market[]"][value="supply"]').check()
    await page.locator('input[name="itemTitle"]').fill(str(account["productName"]))
    keywords = request.get("keywordItems") or [value.strip() for value in str(request.get("keywords") or "").split(",") if value.strip()]
    keyword_fields = page.locator("input.lKeywordTmp")
    for index, keyword in enumerate(keywords[: await keyword_fields.count()]):
        await keyword_fields.nth(index).fill(str(keyword))
        await keyword_fields.nth(index).press("Tab")
    await _select_category(page, [str(value) for value in request.get("categoryPath", [])])
    await _select_text(page, "#lItemCountrySelect1", "수입산")
    await _select_text(page, "#lItemCountrySelect2", "아시아")
    await _select_text(page, "#lItemCountrySelect3", "중국")
    await page.locator(f'input[name="onlyForAdult"][value="{0 if request.get("minorSalesAllowed") else 1}"]').check()
    domeggook = request.get("domeggook") or {}
    await page.locator('input[name="itemSize"]').fill(str(domeggook.get("volume") or "0x0x0"))
    await page.locator('input[name="itemWeight"]').fill(str(domeggook.get("weightKg") or "0.1"))
    await page.locator('input[name="itemCode"]').fill(str(account["modelName"]))
    await page.locator('input[name="itemCompany"]').fill(str(account["manufacturer"]))
    await page.locator('input[name="itemCustomCode"]').fill(str(account["code"]))
    await page.locator('input[name="itemSafetyCert"][value="0"]').check()
    await page.locator("#lImageNormal").set_input_files(str(image_path))
    await page.wait_for_timeout(700)
    await _keep_requested_category(page)
    await _set_detail_html(page, str(request.get("detailHtml") or ""))
    notice = str(request.get("noticeCategory") or "의류")
    notice_label = "패션잡화(모자/벨트/액세서리 등)" if notice == "패션잡화" else notice
    await _select_text(page, "#lInfoDutySelector", notice_label)
    duty_row = page.locator("#lInfoDutySelector").locator("xpath=ancestor::tr[1]")
    await duty_row.locator('input[type="checkbox"]').last.check()
    await _set_prices(page, int(account["supplyPrice"]))
    await _set_options(page, [str(value) for value in request.get("colors", [])], [str(value) for value in request.get("sizes", [])])
    await _set_shipping(page, int(request.get("shipping", {}).get("fee", 3000)))
    await page.locator('input[name="itemSize"]').fill(str(domeggook.get("volume") or "0x0x0"))
    await page.locator('input[name="itemWeight"]').fill(str(domeggook.get("weightKg") or "0.1"))
    caution = page.locator("#lBtnShowSubmitHelp").locator("xpath=preceding::input[@type='checkbox'][1]")
    await caution.check()


async def _finish_option_registration(page: Page, request: dict[str, Any]) -> None:
    await page.wait_for_timeout(1600)
    body = await page.locator("body").inner_text()
    if "상품옵션등록" not in body:
        raise RuntimeError(f"도매꾹 상품옵션등록 화면으로 이동하지 못했습니다: {page.url}")
    date_fields = page.locator('input[type="text"]')
    dated: list[int] = []
    for index in range(await date_fields.count()):
        value = await date_fields.nth(index).input_value()
        if re.fullmatch(r"20\d{2}[.-]\d{2}[.-]\d{2}", value):
            dated.append(index)
    if len(dated) < 2:
        raise RuntimeError("도매꾹 상품옵션 등록기간 입력란을 찾지 못했습니다.")
    today = datetime.now().date()
    domeggook = request.get("domeggook") or {}
    display_days = int(domeggook.get("displayPeriodDays") or 90)
    extension_days = int(domeggook.get("autoExtensionDays") or 90)
    extension_count = int(domeggook.get("autoExtensionCount") or 100)
    end = today + timedelta(days=display_days)
    separator = "." if "." in await date_fields.nth(dated[0]).input_value() else "-"
    await date_fields.nth(dated[0]).fill(today.strftime(f"%Y{separator}%m{separator}%d"))
    await date_fields.nth(dated[1]).fill(end.strftime(f"%Y{separator}%m{separator}%d"))
    immediate = page.get_by_text("즉시진열", exact=False)
    if await immediate.count():
        await immediate.first.click()
    auto_text = page.get_by_text("기간자동연장설정", exact=False)
    if await auto_text.count():
        await auto_text.first.click()
        auto_box = auto_text.first.locator("xpath=ancestor-or-self::label[1]//input[@type='checkbox']")
        if await auto_box.count() and not await auto_box.is_checked():
            await auto_box.check()
    extension_area = page.get_by_text("자동기간연장", exact=True).locator("xpath=ancestor::*[self::div or self::section][1]")
    if await extension_area.count() == 0:
        extension_area = page.locator("body")
    numeric = extension_area.locator('input[type="text"], input[type="number"]')
    candidates = []
    for index in range(await numeric.count()):
        value = await numeric.nth(index).input_value()
        if re.fullmatch(r"\d*", value):
            candidates.append(index)
    if len(candidates) >= 2:
        await numeric.nth(candidates[-2]).fill(str(extension_days))
        await numeric.nth(candidates[-1]).fill(str(extension_count))
    register = page.get_by_text("상품옵션등록", exact=True)
    await register.last.click()
    await page.wait_for_timeout(700)
    modal_register = page.get_by_text("상품옵션등록", exact=True)
    if await modal_register.count():
        visible = [modal_register.nth(i) for i in range(await modal_register.count()) if await modal_register.nth(i).is_visible()]
        if visible:
            await visible[-1].click()
    await page.wait_for_timeout(1600)


async def run_account(request: dict[str, Any], account_payload: dict[str, Any], preview: bool = False) -> dict[str, Any]:
    site_code = str(account_payload.get("siteCode") or "")
    label = LABELS.get(site_code, site_code)
    product_code = str(account_payload.get("code") or "")
    account = _account(site_code)
    if account is None:
        return {"site": label, "siteCode": site_code, "success": False, "productCode": product_code, "error": "도매꾹 계정 설정이 없습니다."}
    work_dir = Path(tempfile.mkdtemp(prefix=f"domeggook-register-{site_code}-", dir=config.DOWNLOAD_DIR))
    dialogs: list[str] = []
    try:
        image_path = _download_main_image(account_payload, work_dir)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=config.HEADLESS)
            context = await browser.new_context(viewport={"width": 1800, "height": 1200})
            page = await context.new_page()

            async def accept_dialog(dialog) -> None:
                dialogs.append(dialog.message)
                await dialog.accept()

            page.on("dialog", lambda dialog: asyncio.create_task(accept_dialog(dialog)))
            try:
                await _login(page, account)
                if await _already_registered(page, product_code):
                    return {"site": label, "siteCode": site_code, "success": True, "alreadyRegistered": True, "productCode": product_code, "message": f"이미 등록된 상품입니다: {product_code}"}
                await _fill_form(page, request, account_payload, image_path)
                if preview:
                    return {"site": label, "siteCode": site_code, "success": True, "preview": True, "productCode": product_code, "message": "도매꾹 필수값 자동입력 검증 완료(최종 등록 전 중단)"}
                register = page.get_by_text("상품등록", exact=True)
                await register.last.click()
                await _finish_option_registration(page, request)
                if await _already_registered(page, product_code):
                    return {"site": label, "siteCode": site_code, "success": True, "productCode": product_code, "message": f"상품등록 및 상품옵션등록 완료: {product_code}"}
                raise RuntimeError("등록 후 상품관리에서 공급사상품코드를 찾지 못했습니다.")
            finally:
                await browser.close()
    except Exception as exc:
        message = str(exc)
        dialog_text = " / ".join(dialogs[-6:])
        if dialog_text and dialog_text not in message:
            message = f"{message} / 사이트 안내: {dialog_text}"
        return {"site": label, "siteCode": site_code, "success": False, "productCode": product_code, "error": message[:1600]}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
