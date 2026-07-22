from __future__ import annotations

import asyncio
import re
from datetime import date, timedelta
from pathlib import Path

from playwright.async_api import Page, async_playwright

from order_worker import config
from order_worker.sites.invoice_utils import download_invoice_export_with_count


SITE_CODE = "domegod"
LABEL = "도매의신"
USER_ID = "jupraha"
PASSWORD = "hare2580@@"
UPLOAD_URL = "https://www.domesin.com/scm/M_order/ship_excel_insert.html"
RETRY_LOOKBACK_DAYS = 3


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


async def stage_invoice_file(page: Page, file_path: Path, dialog_messages: list[str]) -> None:
    print(f"PROGRESS: [{LABEL}] 송장엑셀등록 페이지 이동...")

    async def handle_dialog(dialog) -> None:
        dialog_messages.append(dialog.message)
        await dialog.accept()

    page.on("dialog", lambda dialog: asyncio.ensure_future(handle_dialog(dialog)))
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


def _parse_count(text: str, labels: str) -> int | None:
    after_label = re.search(
        rf"(?:{labels})(?:\s*건수)?\s*[:：]?\s*([0-9,]+)\s*건",
        text,
        flags=re.IGNORECASE,
    )
    if after_label:
        return int(after_label.group(1).replace(",", ""))

    before_label = re.search(
        rf"([0-9,]+)\s*건(?:이|을|가|은|는)?\s*(?:{labels})",
        text,
        flags=re.IGNORECASE,
    )
    if before_label:
        return int(before_label.group(1).replace(",", ""))
    return None


def calculate_retry_start_date(export_type: str, start_date: str) -> str:
    if export_type != "real":
        return start_date
    parsed = date.fromisoformat(start_date)
    return (parsed - timedelta(days=RETRY_LOOKBACK_DAYS - 1)).isoformat()


def parse_result(text: str, expected_count: int | None = None, dialog_messages: list[str] | None = None) -> dict:
    dialogs = dialog_messages or []
    combined_text = "\n".join([text, *dialogs])
    uploaded = _parse_count(combined_text, r"성공|완료|정상\s*처리|배송\s*처리")
    failed = _parse_count(combined_text, r"실패|오류|에러")

    if uploaded is None:
        success_rows = len(re.findall(r"\t성공(?:\s|$)", combined_text))
        uploaded = success_rows or None
    if failed is None:
        failed_rows = len(re.findall(r"\t(?:실패|오류|에러)(?:\s|$)", combined_text))
        failed = failed_rows or 0

    explicit_success_dialog = any(
        re.search(r"(?:완료되었습니다|정상적으로\s*처리|등록되었습니다)", message)
        for message in dialogs
    )
    already_processed = bool(re.search(r"이미\s*(?:배송|발송|송장|등록).*?(?:처리|완료|등록)", combined_text))
    already_processed_count = 0
    confirmed_count = uploaded or 0

    if expected_count and not failed and uploaded is None and explicit_success_dialog:
        confirmed_count = expected_count
        uploaded = expected_count
    elif expected_count == 1 and not failed and uploaded is None and already_processed:
        already_processed_count = 1
        confirmed_count = 1

    count_matches = expected_count is None or confirmed_count == expected_count
    success = confirmed_count > 0 and failed == 0 and count_matches
    if success:
        message = "송장 업로드 결과를 확인했습니다."
    else:
        message = (
            "도매의신 송장 처리 건수를 확인하지 못했거나 대상 건수와 일치하지 않습니다. "
            f"대상 {expected_count if expected_count is not None else '?'}, "
            f"확인 {confirmed_count}, 실패 {failed}"
        )

    return {
        "success": success,
        "expectedCount": expected_count,
        "uploadedCount": uploaded or 0,
        "confirmedCount": confirmed_count,
        "alreadyProcessedCount": already_processed_count,
        "failedCount": failed,
        "message": message,
        "resultText": combined_text[:1000],
    }


async def submit_upload(page: Page, expected_count: int | None, dialog_messages: list[str]) -> dict:
    print(f"PROGRESS: [{LABEL}] 업로드하기 버튼 클릭...")
    await click_upload_button(page)
    try:
        await page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    await page.wait_for_timeout(2000)
    text = await page.locator("body").inner_text(timeout=10000)
    result = parse_result(text, expected_count=expected_count, dialog_messages=dialog_messages)
    print(f"PROGRESS: [{LABEL}] 업로드 완료 {result['uploadedCount']}건, 실패 {result['failedCount']}건")
    return result


async def run_one(export_type: str, start_date: str, end_date: str, preview: bool = False) -> dict:
    retry_start_date = calculate_retry_start_date(export_type, start_date)
    file_path, expected_count = download_invoice_export_with_count(
        SITE_CODE,
        export_type,
        retry_start_date,
        end_date,
    )
    print(f"PROGRESS: [{LABEL}] 인트라넷 업로드용 엑셀 다운로드 완료: {file_path}")
    print(
        f"PROGRESS: [{LABEL}] 미완료 재확인 범위 {retry_start_date}~{end_date}, "
        f"대상 {expected_count if expected_count is not None else '?'}건"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.HEADLESS)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        dialog_messages: list[str] = []
        try:
            await login(page)
            await stage_invoice_file(page, file_path, dialog_messages)
            await find_upload_button(page)
            if preview:
                print(f"PROGRESS: [{LABEL}] preview 모드: 업로드하기 클릭 전 중지")
                return {
                    "site": LABEL,
                    "siteCode": SITE_CODE,
                    "type": export_type,
                    "success": True,
                    "uploadedCount": 0,
                    "confirmedCount": 0,
                    "expectedCount": expected_count,
                    "failedCount": 0,
                    "message": "엑셀 파일 선택까지 완료했습니다.",
                    "preview": True,
                    "retryStartDate": retry_start_date,
                    "retryEndDate": end_date,
                }

            result = await submit_upload(page, expected_count, dialog_messages)
            return {
                "site": LABEL,
                "siteCode": SITE_CODE,
                "type": export_type,
                "retryStartDate": retry_start_date,
                "retryEndDate": end_date,
                **result,
            }
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
