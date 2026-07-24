"""도매꾹 / F도매꾹 주문서 자동 다운로드
경로: 로그인 > 상품공급사센터 > 발주.발송 > 전체선택 > 발주확인 > 엑셀 다운로드 > 데이터파일 생성요청 > 확인 > 20~50초 후 다운받기
"""
import asyncio
import os
import time

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
                candidate = await first_visible_enabled(
                    frame.locator(DOWNLOAD_BTN_SELECTOR)
                )
                if candidate:
                    elapsed = min(
                        timeout_seconds,
                        max(
                            0,
                            round(timeout_seconds - (deadline - time.monotonic())),
                        ),
                    )
                    print(
                        f"PROGRESS: [{label}] 다운받기 버튼 활성화 확인 "
                        f"({elapsed}초, {attempt}회 확인)"
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
    print(
        f"PROGRESS: [{label}] 파일 생성요청 완료, 다운받기 버튼을 "
        f"최대 {config.DOMEGGOOK_WAIT_SECONDS}초 대기합니다..."
    )

    try:
        download_page, download_button = await wait_for_download_button(
            page,
            label,
            context=context,
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
