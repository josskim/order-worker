from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.invoice_utils import download_invoice_export, parse_success_fail_counts


ACCOUNTS = {
    "domeggook": ("jupraha", "hana2580@@", "도매꾹"),
    "Fdomeggook": ("trustprice", "hana2580@@", "F도매꾹"),
}


async def login(page: Page, user_id: str, password: str, label: str) -> None:
    print(f"PROGRESS: [{label}] 로그인 중...")
    await page.goto("https://domeggook.com/ssl/member/mem_loginForm.php")
    await page.wait_for_load_state("domcontentloaded")
    await page.fill("#idInput", user_id)
    await page.fill("#pwInput", password)
    await page.click("#formLogin > input.formSubmit")
    await page.wait_for_load_state("networkidle")
    if "mem_loginForm" in page.url:
        raise RuntimeError("로그인 실패")


async def open_upload_frame(page: Page, file_path: Path, label: str):
    print(f"PROGRESS: [{label}] 발주·발송 페이지 이동...")
    await page.goto("https://domeggook.com/sc/order/lstInprocess", wait_until="networkidle")
    page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))

    print(f"PROGRESS: [{label}] 송장 엑셀일괄입력 모달 열기...")
    await page.click('a[data-action="shipXls"]', timeout=10000)
    await page.wait_for_timeout(1000)

    frame = None
    for candidate in page.frames:
        if "shipXlsFrm" in candidate.url:
            frame = candidate
            break
    if frame is None:
        await page.wait_for_selector('iframe[name="gLayerIframe"]', timeout=10000)
        frame = page.frame(name="gLayerIframe")
    if frame is None:
        raise RuntimeError("송장 엑셀일괄입력 프레임을 찾지 못했습니다.")

    print(f"PROGRESS: [{label}] 엑셀 파일 선택: {file_path.name}")
    await frame.set_input_files("#lAttach", str(file_path))
    return frame


async def submit_upload(frame, label: str) -> dict:
    print(f"PROGRESS: [{label}] 업로드 버튼 클릭...")
    await frame.click("#uploadButton", timeout=10000)
    await frame.page.wait_for_timeout(3000)

    try:
        await frame.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass

    text = await frame.locator("body").inner_text(timeout=10000)
    success_count, failed_count = parse_success_fail_counts(text)
    success_count = success_count or 0
    failed_count = failed_count or 0

    return {
        "success": failed_count == 0,
        "uploadedCount": success_count,
        "failedCount": failed_count,
        "message": "송장 엑셀 업로드 결과를 확인했습니다.",
        "resultText": text[:1000],
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
            frame = await open_upload_frame(page, file_path, label)
            if preview:
                print(f"PROGRESS: [{label}] preview 모드: 업로드 버튼 클릭 전 중지")
                return {
                    "site": label,
                    "siteCode": site,
                    "type": export_type,
                    "success": True,
                    "uploadedCount": 0,
                    "failedCount": 0,
                    "message": "엑셀 파일 선택까지 완료했습니다.",
                    "preview": True,
                }

            result = await submit_upload(frame, label)
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
