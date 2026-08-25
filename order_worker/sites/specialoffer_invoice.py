from __future__ import annotations

import asyncio
import re
from pathlib import Path

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from order_worker import config
from order_worker.sites.invoice_utils import download_invoice_export_with_count


SITE_CODE = "special"
LABEL = "스페셜오퍼"
USER_ID = "jupraha"
PASSWORD = "hare2580@@"


async def login(page: Page) -> None:
    print(f"PROGRESS: [{LABEL}] 로그인 중...")
    await page.goto("https://specialoffer.kr/bbs/login.php", wait_until="domcontentloaded", timeout=45000)
    await page.locator("#login_id").wait_for(state="visible", timeout=20000)
    await page.fill("#login_id", USER_ID)
    await page.fill("#login_pw", PASSWORD)
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            await page.click("#login_fld > dl > dd:nth-child(5) > button")
    except PlaywrightTimeoutError:
        # 로그인 요청이 XHR/스크립트 리다이렉트로 끝나는 경우도 있어 URL과 폼 상태로 확인한다.
        pass
    if "/bbs/login.php" in page.url and await page.locator("#login_id").is_visible():
        raise RuntimeError("스페셜오퍼 로그인 후에도 로그인 화면에 머물러 있습니다.")


async def close_popup(page: Page) -> None:
    try:
        popup_close = "#modal > h1 > button"
        if await page.locator(popup_close).count() > 0:
            await page.click(popup_close)
    except Exception:
        pass


async def stage_invoice_file(page: Page, file_path: Path) -> None:
    print(f"PROGRESS: [{LABEL}] 엑셀일괄배송처리 페이지 이동...")
    await page.goto(
        "https://specialoffer.kr/mypage/page.php?code=seller_odr_3_excel",
        wait_until="domcontentloaded",
        timeout=45000,
    )
    await close_popup(page)
    page.on("dialog", lambda dialog: asyncio.ensure_future(dialog.accept()))

    print(f"PROGRESS: [{LABEL}] 엑셀 파일 선택: {file_path.name}")
    file_input = page.locator('input[name="excelfile"]')
    await file_input.wait_for(state="attached", timeout=20000)
    await file_input.set_input_files(str(file_path))


def parse_result(text: str, expected_count: int | None = None) -> dict:
    total_match = re.search(r"총\s*배송\s*건수\s*[:：]?\s*([0-9,]+)\s*건", text)
    success_match = re.search(r"(?:완료\s*건수|완료|성공)\s*[:：]?\s*([0-9,]+)\s*건", text)
    failed_match = re.search(r"(?:실패\s*건수|실패)\s*[:：]?\s*([0-9,]+)\s*건", text)
    total = int(total_match.group(1).replace(",", "")) if total_match else None
    uploaded = int(success_match.group(1).replace(",", "")) if success_match else 0
    failed = int(failed_match.group(1).replace(",", "")) if failed_match else 0

    failed_serials = re.findall(r"일련번호\s*[:：]?\s*([0-9A-Za-z_-]+)", text)
    count_matches_export = expected_count is None or expected_count == uploaded
    success = (
        success_match is not None
        and failed == 0
        and (total is None or total == uploaded)
        and count_matches_export
    )
    return {
        "success": success,
        "totalCount": total,
        "uploadedCount": uploaded,
        "failedCount": failed,
        "failedSerials": failed_serials,
        "message": (
            "배송정보 등록 결과를 확인했습니다."
            if success
            else (
                "배송정보 처리 건수가 일치하지 않습니다. "
                f"대상 {expected_count}, 총 {total}, 완료 {uploaded}, 실패 {failed}"
            )
        ),
        "resultText": text[:1000],
    }


async def submit_upload(page: Page, expected_count: int | None) -> dict:
    print(f"PROGRESS: [{LABEL}] 배송정보 등록 클릭...")
    submit = page.locator('input[type="submit"][value*="배송정보"]')
    await submit.wait_for(state="visible", timeout=20000)
    try:
        async with page.expect_navigation(wait_until="domcontentloaded", timeout=30000):
            await submit.click()
    except PlaywrightTimeoutError:
        # 결과가 같은 페이지에 비동기로 표시되는 경우 아래 결과 폴링으로 확인한다.
        pass

    text = ""
    result = parse_result(text, expected_count)
    for _ in range(60):
        text = await page.locator("body").inner_text(timeout=10000)
        result = parse_result(text, expected_count)
        if result["success"] or result["totalCount"] is not None or result["failedCount"] > 0:
            break
        await asyncio.sleep(1)
    print(f"PROGRESS: [{LABEL}] 등록 완료 {result['uploadedCount']}건, 실패 {result['failedCount']}건")
    return result


async def run_one(export_type: str, start_date: str, end_date: str, preview: bool = False) -> dict:
    file_path, expected_count = download_invoice_export_with_count(
        SITE_CODE,
        export_type,
        start_date,
        end_date,
    )
    print(f"PROGRESS: [{LABEL}] 인트라넷 업로드용 엑셀 다운로드 완료: {file_path}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.HEADLESS)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        try:
            await login(page)
            await stage_invoice_file(page, file_path)
            if preview:
                print(f"PROGRESS: [{LABEL}] preview 모드: 배송정보 등록 전 중지")
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

            result = await submit_upload(page, expected_count)
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
