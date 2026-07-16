"""스페셜오퍼 주문서 자동 다운로드
경로: 로그인 > 마이페이지 이동 > 팝업 닫기 > 입금완료 메뉴 > 발주확인 > 배송준비 메뉴 > 엑셀 저장
"""
import asyncio
import os
from playwright.async_api import async_playwright
from order_worker import config
from order_worker.sites.utils import DOWNLOAD_DIR, upload_to_intranet

SITE_CODE = "special"
LABEL = "스페셜오퍼"
USER_ID = "jupraha"
PASSWORD = "hare2580@@"

async def run_one(page, context):
    print(f"PROGRESS: [{LABEL}] 로그인 중...")
    await page.goto("https://specialoffer.kr/bbs/login.php")
    await page.wait_for_load_state("domcontentloaded")
    
    # 로그인 정보 입력
    await page.fill("#login_id", USER_ID)
    await page.fill("#login_pw", PASSWORD)
    await page.click("#login_fld > dl > dd:nth-child(5) > button")
    await page.wait_for_load_state("networkidle")
    print(f"PROGRESS: [{LABEL}] 로그인 완료")

    # 관리자/마이페이지 이동
    await page.goto("https://specialoffer.kr/mypage/page.php?code=seller_main")
    await page.wait_for_load_state("networkidle")

    # 팝업 닫기
    try:
        popup_close = "#modal > h1 > button"
        if await page.locator(popup_close).count() > 0:
            await page.click(popup_close)
            print(f"PROGRESS: [{LABEL}] 팝업 닫기 완료")
    except:
        pass

    # 다이얼로그 자동 수락 (발주확인 클릭 시 등)
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

    # 1. 입금완료(배송요청) 클릭 및 발주확인
    print(f"PROGRESS: [{LABEL}] 입금완료 메뉴 이동 중...")
    await page.goto(
        "https://specialoffer.kr/mypage/page.php?code=seller_odr_2",
        wait_until="networkidle",
    )

    # 전체 체크박스 클릭 후 발주확인 (주문이 있을 때만)
    order_checkboxes = page.locator('input[name="chk[]"]')
    order_count = await order_checkboxes.count()
    if order_count > 0:
        print(f"PROGRESS: [{LABEL}] 신규 주문 {order_count}건, 배송준비 처리 중...")
        for checkbox in await page.locator('input[name="it_sel[]"]').all():
            await checkbox.check()
        for checkbox in await order_checkboxes.all():
            await checkbox.check()
        await page.locator('input[type="submit"][value="배송준비"]').click()
        await page.wait_for_load_state("networkidle")
        remaining_count = await page.locator('input[name="chk[]"]').count()
        if remaining_count >= order_count:
            raise RuntimeError(
                f"배송준비 상태 변경을 확인하지 못했습니다. "
                f"처리 전 {order_count}건, 처리 후 {remaining_count}건"
            )
        print(f"PROGRESS: [{LABEL}] 배송준비 처리 완료: {order_count - remaining_count}건")

    # 2. 배송준비 클릭
    print(f"PROGRESS: [{LABEL}] 배송준비 메뉴 이동 중...")
    await page.goto(
        "https://specialoffer.kr/mypage/page.php?code=seller_odr_3",
        wait_until="networkidle",
    )

    # 3. 검색결과 엑셀저장
    print(f"PROGRESS: [{LABEL}] 엑셀 다운로드 시도 중...")
    excel_btn = 'a[href*="seller_odr_excel.php?code=seller_odr_3"]'
    
    try:
        button = page.locator(excel_btn)
        if await button.count() == 0:
            print(f"  [{LABEL}] 엑셀 버튼 없음 (주문 없음)")
            return {"site": LABEL, "success": True, "totalRows": 0, "insertedCount": 0}

        async with page.expect_download(timeout=30000) as dl:
            await button.click(no_wait_after=True, timeout=15000)
            
        download = await dl.value
        save_path = os.path.join(DOWNLOAD_DIR, download.suggested_filename or "specialoffer_orders.xls")
        await download.save_as(save_path)
        print(f"PROGRESS: [{LABEL}] 다운로드 완료: {save_path}")
        
        result = upload_to_intranet(save_path, SITE_CODE)
        return {"site": LABEL, **result}
    except Exception as e:
        # "출력할 자료가 없습니다" 알림창 등으로 인한 실패 처리
        print(f"  [{LABEL}] 엑셀 다운로드 불가 (주문 없음 추정): {str(e)}")
        return {"site": LABEL, "success": True, "totalRows": 0, "insertedCount": 0}

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.HEADLESS)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        try:
            r = await run_one(page, context)
        except Exception as e:
            r = {"site": LABEL, "success": False, "error": str(e)}
        await browser.close()
    return [r]
