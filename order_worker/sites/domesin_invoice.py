from __future__ import annotations

import asyncio
import re
from pathlib import Path

from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.invoice_utils import download_invoice_export


SITE_CODE = "domegod"
LABEL = "도매의신"
USER_ID = "jupraha"
PASSWORD = "hare2580@@"
UPLOAD_URL = "https://www.domesin.com/scm/M_order/ship_excel_insert.html"


async def login(page: Page) -> None:
    print(f"PROGRESS: [{LABEL}] 로그인 중...")
    await page.goto("https://www.domesin.com/scm/login.html")
    await page.wait_for_load_state("domcontentloaded")
    await page.fill("body > div > form > input[type=text]:nth-child(4)", USER_ID)
    await page.fill("body > div > form > input[type=password]:nth-child(5)", PASSWORD)
    await page.click("body > div > form > button.login-btn")
    await page.wait_for_load_state("networkidle")
    if "login.html" in page.url:
        raise RuntimeError("로그인 실패")


async def stage_invoice_file(page: Page, file_path: Path) -> None:
    print(f"PROGRESS: [{LABEL}] 송장엑셀등록 페이지 이동...")
    page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))
    await page.goto(UPLOAD_URL, wait_until="networkidle")

    print(f"PROGRESS: [{LABEL}] 엑셀 파일 선택: {file_path.name}")
    await page.set_input_files('input[type="file"]', str(file_path))


async def click_upload_button(page: Page) -> None:
    locator = await find_upload_button(page)
    await locator.click(timeout=10000)


async def find_upload_button(page: Page):
    candidates = [
        'input[type="submit"][value*="업로드"]',
        'button:has-text("업로드하기")',
        'input[type="button"][value*="업로드"]',
        'a:has-text("업로드하기")',
        'text=업로드하기',
    ]
    for selector in candidates:
        locator = page.locator(selector).first
        try:
            if await locator.count() > 0:
                return locator
        except Exception:
            continue
    raise RuntimeError("업로드하기 버튼을 찾지 못했습니다.")


def parse_result(text: str) -> dict:
    success_match = re.search(r"(?:성공|완료)\s*[:：]?\s*([0-9,]+)\s*건", text)
    failed_match = re.search(r"(?:실패|오류|에러)\s*[:：]?\s*([0-9,]+)\s*건", text)
    uploaded = int(success_match.group(1).replace(",", "")) if success_match else 0
    failed = int(failed_match.group(1).replace(",", "")) if failed_match else 0
    if not uploaded:
        uploaded = len(re.findall(r"\t성공(?:\s|$)", text))
    if not failed:
        failed = len(re.findall(r"\t(?:실패|오류|에러)(?:\s|$)", text))

    return {
        "success": failed == 0,
        "uploadedCount": uploaded,
        "failedCount": failed,
        "message": "송장 업로드 결과를 확인했습니다.",
        "resultText": text[:1000],
    }


async def submit_upload(page: Page) -> dict:
    print(f"PROGRESS: [{LABEL}] 업로드하기 버튼 클릭...")
    await click_upload_button(page)
    try:
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    text = await page.locator("body").inner_text(timeout=10000)
    result = parse_result(text)
    print(f"PROGRESS: [{LABEL}] 업로드 완료 {result['uploadedCount']}건, 실패 {result['failedCount']}건")
    return result


async def run_one(export_type: str, start_date: str, end_date: str, preview: bool = False) -> dict:
    file_path = download_invoice_export(SITE_CODE, export_type, start_date, end_date)
    print(f"PROGRESS: [{LABEL}] 인트라넷 업로드용 엑셀 다운로드 완료: {file_path}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.HEADLESS)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        try:
            await login(page)
            await stage_invoice_file(page, file_path)
            await find_upload_button(page)
            if preview:
                print(f"PROGRESS: [{LABEL}] preview 모드: 업로드하기 클릭 전 중지")
                return {
                    "site": LABEL,
                    "siteCode": SITE_CODE,
                    "type": export_type,
                    "success": True,
                    "uploadedCount": 0,
                    "failedCount": 0,
                    "message": "엑셀 파일 선택까지 완료했습니다.",
                    "preview": True,
                }

            result = await submit_upload(page)
            return {"site": LABEL, "siteCode": SITE_CODE, "type": export_type, **result}
        finally:
            await browser.close()


async def run(site_names: list[str], export_type: str, start_date: str, end_date: str, preview: bool = False) -> list[dict]:
    results: list[dict] = []
    for _site in site_names:
        try:
            results.append(await run_one(export_type, start_date, end_date, preview=preview))
        except Exception as exc:
            results.append({"site": LABEL, "siteCode": SITE_CODE, "type": export_type, "success": False, "error": str(exc)})
    return results
