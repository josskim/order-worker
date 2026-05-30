from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.invoice_utils import download_invoice_export, parse_ownerclan_result


ACCOUNTS = {
    "ownerclan": ("2010019378", "hare2580@@##", "오너클랜"),
    "Fownerclan": ("2010024730", "hare2580@@##", "F오너클랜"),
}


async def login(page: Page, user_id: str, password: str, label: str) -> None:
    print(f"PROGRESS: [{label}] 로그인 중...")
    await page.goto("https://ownerclan.com/vender/login.php")
    await page.wait_for_load_state("domcontentloaded")
    await page.fill('input[name="id"]', user_id)
    await page.fill('input[name="passwd"]', password)
    await page.click('input[type="submit"]')
    await page.wait_for_load_state("networkidle")


async def click_first_visible(page: Page, selectors: list[str], timeout: int = 10000) -> None:
    last_error: Exception | None = None
    for selector in selectors:
        try:
            locator = page.locator(selector).first
            await locator.wait_for(state="visible", timeout=timeout)
            await locator.click()
            return
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"클릭할 버튼을 찾지 못했습니다: {last_error}")


async def upload_file(page: Page, file_path: Path, label: str) -> None:
    print(f"PROGRESS: [{label}] 송장 업로드 페이지 이동...")
    await page.goto("https://ownerclan.com/vender/order_excel_upload.php", wait_until="networkidle")
    page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))

    print(f"PROGRESS: [{label}] 엑셀 파일 선택: {file_path.name}")
    await page.set_input_files('input[type="file"]', str(file_path))

    print(f"PROGRESS: [{label}] 등록하기 클릭...")
    await click_first_visible(
        page,
        [
            'a[href*="CheckForm"]',
            'input[type="submit"]',
            'input[type="button"][value*="등록"]',
            'button:has-text("등록하기")',
            'a:has-text("등록하기")',
            'img[alt*="등록"]',
        ],
    )
    await page.wait_for_load_state("networkidle")


async def submit_shipping_info(page: Page, label: str) -> dict:
    print(f"PROGRESS: [{label}] 배송정보 등록 버튼 확인...")
    shipping_selectors = [
        'a[href*="delivery_pop"]',
        'input[value*="배송정보"]',
        'button:has-text("배송정보")',
        'a:has-text("배송정보")',
        'img[alt*="배송정보"]',
        'text=배송정보 등록',
        'text=배송정보등록',
    ]
    clicked = False
    try:
        async with page.expect_popup(timeout=15000) as popup_info:
            await click_first_visible(page, shipping_selectors, timeout=15000)
            clicked = True
        popup = await popup_info.value
        await popup.wait_for_load_state("networkidle")
        result_text = await popup.locator("body").inner_text(timeout=10000)
        await popup.close()
    except Exception:
        if not clicked:
            await click_first_visible(page, shipping_selectors, timeout=15000)
        await page.wait_for_load_state("networkidle")
        result_text = await page.locator("body").inner_text(timeout=10000)

    result = parse_ownerclan_result(result_text)
    print(f"PROGRESS: [{label}] 배송처리 성공 {result['uploadedCount']}건, 실패 {result['failedCount']}건")
    return result


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
            await upload_file(page, file_path, label)
            if preview:
                print(f"PROGRESS: [{label}] preview 모드: 배송정보 등록 전 중지")
                return {
                    "site": label,
                    "siteCode": site,
                    "type": export_type,
                    "success": True,
                    "uploadedCount": 0,
                    "failedCount": 0,
                    "message": "엑셀 업로드 화면 확인까지만 완료했습니다.",
                    "preview": True,
                }
            result = await submit_shipping_info(page, label)
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
