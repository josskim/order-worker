from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.invoice_utils import download_invoice_export
from order_worker.sites.onchannel import dismiss_popups


ACCOUNTS = {
    "onch3": ("trustprice@naver.com", "hana2580@@", "온채널"),
    "Fonch3": ("youby74@naver.com", "hana2580@@", "F온채널"),
}


async def login(page: Page, user_id: str, password: str, label: str) -> None:
    print(f"PROGRESS: [{label}] 로그인 중...")
    await page.goto("https://www.onch3.co.kr/login/login_web.php")
    await page.wait_for_load_state("domcontentloaded")
    await page.fill('input[name="username"]', user_id, timeout=10000)
    await page.fill('input[name="password"]', password, timeout=10000)
    await page.click("button.submit-btn", timeout=10000)
    await page.wait_for_load_state("networkidle", timeout=30000)
    if "login_web.php" in page.url:
        raise RuntimeError("로그인 실패")


async def set_checked(page: Page, selector: str) -> None:
    await page.evaluate(
        """(selector) => {
            const checkbox = document.querySelector(selector);
            if (!checkbox) return;
            checkbox.checked = true;
            checkbox.dispatchEvent(new Event('input', { bubbles: true }));
            checkbox.dispatchEvent(new Event('change', { bubbles: true }));
        }""",
        selector,
    )


async def stage_invoice_file(page: Page, file_path: Path, label: str) -> Page:
    print(f"PROGRESS: [{label}] 배송준비 페이지 이동...")
    await page.goto("https://www.onch3.co.kr/supplier/orders.php?state=preparing", wait_until="networkidle")
    page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))
    await dismiss_popups(page)

    print(f"PROGRESS: [{label}] 엑셀송장등록 모달 열기...")
    await page.locator('button[onclick*="supplierOrderDeliveryExcelModal"]').first.click(timeout=10000)
    await page.wait_for_selector("#supplierOrderDeliveryExcelModal", state="visible", timeout=10000)

    print(f"PROGRESS: [{label}] 엑셀 파일 선택: {file_path.name}")
    await page.set_input_files("#excelFileUpload", str(file_path))

    print(f"PROGRESS: [{label}] 동의 체크 후 등록하러가기 클릭...")
    await set_checked(page, "#agreement-order-excel-check")

    async with page.expect_popup(timeout=30000) as popup_info:
        await page.click("#btn-order-excel-regist", timeout=10000)

    popup = await popup_info.value
    await popup.wait_for_load_state("networkidle", timeout=30000)
    return popup


async def submit_invoice_popup(popup: Page, label: str) -> dict:
    print(f"PROGRESS: [{label}] 송장번호 등록하기 클릭...")
    loop = asyncio.get_running_loop()
    dialog_future = loop.create_future()
    row_count = await popup.locator("input[name='pcode']").count()

    async def accept_dialog(dialog):
        if not dialog_future.done():
            dialog_future.set_result(dialog.message)
        await dialog.accept()

    popup.on("dialog", accept_dialog)
    await popup.locator("button.st").first.click(timeout=15000)

    try:
        if await popup.locator(".cancel_order_modal:visible").count() > 0:
            await popup.click("#registTrackingNum", timeout=5000)
    except Exception:
        pass

    try:
        text = await asyncio.wait_for(dialog_future, timeout=90)
    except asyncio.TimeoutError:
        try:
            text = await popup.locator("body").inner_text(timeout=5000)
        except Exception:
            text = ""

    success = "완료" in text or "성공" in text or not text
    return {
        "success": success,
        "uploadedCount": row_count if success else 0,
        "failedCount": 0 if success else 1,
        "message": text or "송장번호 등록 요청을 완료했습니다.",
    }


async def run_one(site: str, export_type: str, start_date: str, end_date: str, preview: bool = False) -> dict:
    user_id, password, label = ACCOUNTS[site]
    file_path = download_invoice_export(site, export_type, start_date, end_date)
    print(f"PROGRESS: [{label}] 인트라넷 업로드용 엑셀 다운로드 완료: {file_path}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.HEADLESS)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        try:
            await login(page, user_id, password, label)
            popup = await stage_invoice_file(page, file_path, label)
            if preview:
                print(f"PROGRESS: [{label}] preview 모드: 송장번호 등록하기 전 중지")
                return {
                    "site": label,
                    "siteCode": site,
                    "type": export_type,
                    "success": True,
                    "uploadedCount": 0,
                    "failedCount": 0,
                    "message": "새창 확인까지 완료했습니다.",
                    "preview": True,
                }

            result = await submit_invoice_popup(popup, label)
            return {"site": label, "siteCode": site, "type": export_type, **result}
        finally:
            await browser.close()


async def run(site_names: list[str], export_type: str, start_date: str, end_date: str, preview: bool = False) -> list[dict]:
    results: list[dict] = []
    for site in site_names:
        try:
            results.append(await run_one(site, export_type, start_date, end_date, preview=preview))
        except Exception as exc:
            label = ACCOUNTS.get(site, (None, None, site))[2]
            results.append({"site": label, "siteCode": site, "type": export_type, "success": False, "error": str(exc)})
    return results
