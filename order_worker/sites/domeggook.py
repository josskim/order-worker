"""도매꾹 / F도매꾹 주문서 자동 다운로드
경로: 로그인 > 상품공급사센터 > 발주.발송 > 전체선택 > 발주확인 > 엑셀 다운로드 > 데이터파일 생성요청 > 확인 > 20~50초 후 다운받기
"""
import asyncio
import os
import re
import time
from datetime import datetime, timedelta, timezone

from playwright.async_api import (
    Error as PlaywrightError,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)
from order_worker import config
from order_worker.sites.utils import DOWNLOAD_DIR, upload_to_intranet

ACCOUNTS = [
    ("domeggook",  "jupraha",     "hana2580@@", "도매꾹"),
    ("Fdomeggook", "trustprice",  "hana2580@@", "F도매꾹"),
]


DOWNLOAD_BTN_SELECTOR = (
    "a:has-text('다운받기'), "
    "#lGrid > div > div.tui-grid-content-area.tui-grid-no-scroll-x"
    " > div.tui-grid-rside-area > div.tui-grid-body-area > div"
    " > div.tui-grid-table-container > table > tbody"
    " > tr.tui-grid-row-odd.tui-grid-cell-current-row"
    " > td:nth-child(3) > div > a"
)
KST = timezone(timedelta(hours=9), name="KST")
DOWNLOAD_ROW_TIME_PATTERN = re.compile(
    r"(20\d{2}-\d{2}-\d{2})\s+(\d{2}:\d{2}:\d{2})"
)
ORDER_LIST_COUNT_PATTERN = re.compile(
    r"발주\s*[·.ㆍ]?\s*발송\s*목록\s*\(\s*총\s*([\d,]+)\s*건\s*\)"
)


async def first_visible_enabled(locator):
    count = await locator.count()
    for index in range(count):
        candidate = locator.nth(index)
        try:
            if await candidate.is_visible() and await candidate.is_enabled():
                return candidate
        except PlaywrightError:
            continue
    return None

def parse_order_list_count(text):
    """발주·발송 목록 제목에서 현재 주문 건수를 읽는다."""
    match = ORDER_LIST_COUNT_PATTERN.search(text or "")
    return int(match.group(1).replace(",", "")) if match else None


async def detect_order_list_count(page, timeout_seconds=15, poll_seconds=0.5):
    """목록 건수 또는 실제 그리드 행을 확인하고, 빈 목록은 0으로 반환한다."""
    deadline = time.monotonic() + timeout_seconds
    body_text = ""

    while time.monotonic() < deadline:
        try:
            body_text = await page.locator("body").inner_text()
            parsed = parse_order_list_count(body_text)
            if parsed is not None:
                return parsed

            rows = page.locator("#lGrid .tui-grid-body-area tbody tr")
            row_count = await rows.count()
            if row_count > 0:
                return row_count
        except PlaywrightError:
            pass

        await asyncio.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))

    # 발주·발송 화면까지 진입했지만 목록 영역/행이 끝내 생성되지 않은 경우도
    # 사이트의 빈 목록 표현으로 본다. 로그인 실패 페이지는 여기서 성공 처리하지 않는다.
    if "발주" in body_text and "발송" in body_text:
        return 0
    return None


def no_order_result(label):
    return {
        "site": label,
        "success": True,
        "noData": True,
        "message": "주문서 없음",
        "totalRows": 0,
        "insertedCount": 0,
        "duplicateCount": 0,
    }



async def download_row_timestamp(candidate):
    try:
        row_text = await candidate.locator("xpath=ancestor::tr[1]").inner_text()
    except PlaywrightError:
        return None

    matches = DOWNLOAD_ROW_TIME_PATTERN.findall(row_text or "")
    if not matches:
        return None

    parsed = []
    for date_text, time_text in matches:
        try:
            parsed.append(
                datetime.strptime(
                    f"{date_text} {time_text}",
                    "%Y-%m-%d %H:%M:%S",
                ).replace(tzinfo=KST)
            )
        except ValueError:
            continue
    # 표 컬럼 순서는 요청일시, 처리일시다. 처리 완료가 늦은 예전 파일이
    # 새 요청보다 먼저 선택되지 않도록 요청일시(첫 시각)를 기준으로 삼는다.
    return parsed[0] if parsed else None


async def latest_visible_download(locator, not_before=None):
    candidates = []
    fallback = None
    count = await locator.count()
    for index in range(count):
        candidate = locator.nth(index)
        try:
            if not await candidate.is_visible() or not await candidate.is_enabled():
                continue
        except PlaywrightError:
            continue

        fallback = fallback or candidate
        row_timestamp = await download_row_timestamp(candidate)
        if row_timestamp is None:
            continue
        if not_before and row_timestamp < not_before - timedelta(minutes=2):
            continue
        candidates.append((row_timestamp, candidate))

    if candidates:
        return max(candidates, key=lambda item: item[0])
    if not_before:
        return None
    return (None, fallback) if fallback else None


async def wait_for_action_target(context, selector, timeout_seconds, label):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        for candidate_page in reversed(context.pages):
            for frame in candidate_page.frames:
                candidate = await first_visible_enabled(frame.locator(selector))
                if candidate:
                    return candidate_page, frame, candidate
        await asyncio.sleep(1)
    raise PlaywrightTimeoutError(
        f"{selector} 버튼이 {timeout_seconds}초 안에 나타나지 않았습니다."
    )


async def wait_for_download_button(
    page,
    label,
    context=None,
    timeout_seconds=None,
    poll_seconds=None,
    not_before=None,
):
    timeout_seconds = timeout_seconds or config.DOMEGGOOK_WAIT_SECONDS
    poll_seconds = poll_seconds or config.DOMEGGOOK_POLL_SECONDS
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    last_error = ""

    while time.monotonic() < deadline:
        attempt += 1
        candidate_pages = reversed(context.pages) if context else [page]
        for candidate_page in candidate_pages:
            for frame in candidate_page.frames:
                selected = await latest_visible_download(
                    frame.locator(DOWNLOAD_BTN_SELECTOR),
                    not_before=not_before,
                )
                if selected:
                    row_timestamp, candidate = selected
                    elapsed = min(
                        timeout_seconds,
                        max(
                            0,
                            round(timeout_seconds - (deadline - time.monotonic())),
                        ),
                    )
                    print(
                        f"PROGRESS: [{label}] 다운받기 버튼 활성화 확인 "
                        f"({elapsed}초, {attempt}회 확인"
                        f"{f', 생성시각 {row_timestamp:%Y-%m-%d %H:%M:%S}' if row_timestamp else ''})"
                    )
                    return candidate_page, candidate

        elapsed = min(
            timeout_seconds,
            max(0, round(timeout_seconds - (deadline - time.monotonic()))),
        )
        print(
            f"PROGRESS: [{label}] 엑셀 생성 대기 중... "
            f"({elapsed}/{timeout_seconds}초, {attempt}회 확인)"
        )
        await asyncio.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
        if time.monotonic() >= deadline:
            break
        try:
            await page.reload(wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(500)
        except PlaywrightError as exc:
            last_error = str(exc)
            print(
                f"  [{label}] 생성 상태 새로고침 일시 실패, 계속 대기합니다: "
                f"{last_error}"
            )

    detail = f" / 마지막 새로고침 오류: {last_error}" if last_error else ""
    raise PlaywrightTimeoutError(
        f"다운받기 버튼이 {timeout_seconds}초 동안 활성화되지 않았습니다{detail}"
    )


async def run_one(site_code, user_id, password, label, page, context):
    print(f"PROGRESS: [{label}] 로그인 중...")
    await page.goto("https://domeggook.com/ssl/member/mem_loginForm.php")
    await page.wait_for_load_state("domcontentloaded")

    # 로그인
    await page.fill("#idInput", user_id)
    await page.fill("#pwInput", password)
    await page.click("#formLogin > input.formSubmit")
    await page.wait_for_load_state("networkidle")
    print(f"PROGRESS: [{label}] 로그인 완료")

    # 다이얼로그 자동 처리
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

    # 상품공급사센터 클릭
    await page.click("#rightMenu > li:nth-child(6) > a")
    await page.wait_for_load_state("networkidle")
    print(f"PROGRESS: [{label}] 상품공급사센터 이동 완료")

    # 발주.발송 클릭
    await page.click("#orderStatusZone > div.pContent > div.halfZone.pLeft > ul > li:nth-child(2)")
    await page.wait_for_load_state("networkidle")
    print(f"PROGRESS: [{label}] 발주.발송 페이지 이동 완료")

    order_count = await detect_order_list_count(page)
    if order_count == 0:
        print(f"PROGRESS: [{label}] 발주·발송 목록 0건 - 주문서 없음")
        return no_order_result(label)
    if order_count is None:
        return {
            "site": label,
            "success": False,
            "error": "발주·발송 목록의 주문 건수를 확인하지 못했습니다.",
        }
    print(f"PROGRESS: [{label}] 발주·발송 목록 {order_count}건 확인")

    # 전체선택 체크박스 클릭
    print(f"PROGRESS: [{label}] 전체선택 체크박스 클릭 중...")
    checkbox_selector = (
        "#lGrid > div > div.tui-grid-content-area > div.tui-grid-lside-area"
        " > div.tui-grid-header-area > table > tbody > tr"
        " > th.tui-grid-cell.tui-grid-cell-header.tui-grid-cell-row-header"
        " > span > input[type=checkbox]"
    )
    try:
        await page.wait_for_selector(checkbox_selector, timeout=10000)
        await page.click(checkbox_selector)
    except:
        # 셀렉터 실패 시 텍스트 기반 시도
        await page.evaluate("document.querySelectorAll('input[type=\"checkbox\"]').forEach(c => c.checked = true)")
    
    await asyncio.sleep(1)

    # 발주확인 클릭
    print(f"PROGRESS: [{label}] 발주확인 클릭 중...")
    await page.click("#lList > div.pFunctions > a:nth-child(3)")
    await page.wait_for_load_state("networkidle")

    # 엑셀 다운로드 클릭 (모달/팝업 감지)
    print(f"PROGRESS: [{label}] 엑셀 다운로드 클릭 (모달 대기)...")
    try:
        _, _, excel_request_button = await wait_for_action_target(
            context,
            "#lList > div.pHeader > form > a",
            config.DOMEGGOOK_ACTION_WAIT_SECONDS,
            label,
        )
        await excel_request_button.click()
    except PlaywrightTimeoutError as exc:
        return {
            "site": label,
            "success": False,
            "error": f"주문 화면 진입 후 엑셀 다운로드 버튼 대기 실패: {exc}",
        }
    
    # 모달이 나타날 때까지 대기
    submit_btn_selector = "#lXlsReqNoticeBtnSubmit"
    try:
        _target_page, _target, submit_button = await wait_for_action_target(
            context,
            submit_btn_selector,
            config.DOMEGGOOK_ACTION_WAIT_SECONDS,
            label,
        )
        print(f"  [{label}] 엑셀 생성요청 버튼 확인")
    except PlaywrightTimeoutError as exc:
        return {
            "site": label,
            "success": False,
            "error": f"엑셀 생성요청 화면 대기 실패: {exc}",
        }

    # 데이터파일 생성요청 클릭
    requested_at = datetime.now(KST)
    await submit_button.click()
    await asyncio.sleep(1)

    # 확인 클릭
    _, _, close_button = await wait_for_action_target(
        context,
        "#lXlsReqNoticeBtnClose",
        config.DOMEGGOOK_ACTION_WAIT_SECONDS,
        label,
    )
    await close_button.click()
    await asyncio.sleep(1)
    await page.goto(
        "https://domeggook.com/sc/excel/getOrderList",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    print(
        f"PROGRESS: [{label}] 파일 생성요청 완료, 다운받기 버튼을 "
        f"최대 {config.DOMEGGOOK_WAIT_SECONDS}초 대기합니다..."
    )

    try:
        download_page, download_button = await wait_for_download_button(
            page,
            label,
            context=context,
            not_before=requested_at,
        )
    except PlaywrightTimeoutError as exc:
        return {"site": label, "success": False, "error": f"엑셀 생성 시간 초과: {exc}"}

    # 다운받기 클릭
    try:
        async with download_page.expect_download(
            timeout=config.DOMEGGOOK_DOWNLOAD_TIMEOUT_SECONDS * 1000
        ) as dl:
            await download_button.click()

        download = await dl.value
        save_path = os.path.join(
            DOWNLOAD_DIR,
            download.suggested_filename or f"{site_code}_order.xlsx",
        )
        await download.save_as(save_path)
        print(f"PROGRESS: [{label}] 다운로드 완료: {save_path}")
        result = upload_to_intranet(save_path, site_code)
        return {"site": label, **result}
    except Exception as e:
        return {"site": label, "success": False, "error": f"다운로드 실패: {str(e)}"}

async def run():
    results = []
    async with async_playwright() as p:
        for site_code, user_id, password, label in ACCOUNTS:
            browser = await p.chromium.launch(headless=config.HEADLESS)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()
            try:
                r = await run_one(site_code, user_id, password, label, page, context)
                results.append(r)
            except Exception as e:
                results.append({"site": label, "success": False, "error": str(e)})
            await browser.close()
    return results
