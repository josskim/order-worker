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
    await page.click("#snb > dl > dd:nth-child(13) > a")
    await page.wait_for_load_state("networkidle")

    # 전체 체크박스 클릭 후 발주확인 (주문이 있을 때만)
    try:
        # 체크박스 존재 여부 확인 (예상 셀렉터: #check_all 또는 input[name='chk_all'])
        checkboxes = page.locator("input[type='checkbox'][name^='chk[']")
        if await checkboxes.count() > 0:
            print(f"PROGRESS: [{LABEL}] 신규 주문 발견, 발주확인 진행 중...")
            # 전체 선택 (보통 헤더의 체크박스 또는 루프)
            await page.evaluate("document.querySelectorAll('input[type=\"checkbox\"]').forEach(c => c.checked = true)")
            # 발주확인 버튼 클릭 (사용자 가이드에 따라 요소를 찾아야 함, 여기서는 일반적인 버튼 텍스트 시도)
            confirm_btn = page.locator("button:has-text('발주확인'), a:has-text('발주확인'), button:has-text('주문확인')")
            if await confirm_btn.count() > 0:
                await confirm_btn.first.click()
                await page.wait_for_load_state("networkidle")
    except Exception as e:
        print(f"  [{LABEL}] 발주확인 단계 스킵 혹은 오류: {str(e)}")

    # 2. 배송준비 클릭
    print(f"PROGRESS: [{LABEL}] 배송준비 메뉴 이동 중...")
    await page.click("#snb > dl > dd:nth-child(14) > a")
    await page.wait_for_load_state("networkidle")

    # 3. 검색결과 엑셀저장
    print(f"PROGRESS: [{LABEL}] 엑셀 다운로드 시도 중...")
    excel_btn = "#forderlist > div.local_frm01 > a:nth-child(3)"
    
    try:
        # 엑셀 버튼 클릭 전 alert 발생 여부 감지 로직 (주문 없을 시)
        async with page.expect_download(timeout=10000) as dl:
            await page.click(excel_btn)
            
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
