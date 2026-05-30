"""도매꾹 / F도매꾹 주문서 자동 다운로드
경로: 로그인 > 상품공급사센터 > 발주.발송 > 전체선택 > 발주확인 > 엑셀 다운로드 > 데이터파일 생성요청 > 확인 > 20~50초 후 다운받기
"""
import asyncio
import os
from playwright.async_api import async_playwright
from order_worker import config
from order_worker.sites.utils import DOWNLOAD_DIR, upload_to_intranet

ACCOUNTS = [
    ("domeggook",  "jupraha",     "hana2580@@", "도매꾹"),
    ("Fdomeggook", "trustprice",  "hana2580@@", "F도매꾹"),
]

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
        await page.click("#lList > div.pHeader > form > a")
    except:
        # 엑셀 다운로드 버튼 자체가 없는 경우 (주문 0건 등)
        print(f"  [{label}] 엑셀 다운로드 버튼을 찾을 수 없습니다. (주문 없음 추정)")
        return {"site": label, "success": True, "totalRows": 0, "insertedCount": 0}
    
    # 모달이 나타날 때까지 대기
    submit_btn_selector = "#lXlsReqNoticeBtnSubmit"
    try:
        # 1. 현재 페이지 내 모달 확인
        await page.wait_for_selector(submit_btn_selector, state="visible", timeout=7000)
        target = page
        print(f"  [{label}] 페이지 내 모달 확인")
    except:
        # 2. iframe 내에 있는지 확인
        print(f"  [{label}] 페이지 내 모달 없음, iframe/팝업 확인 중...")
        target = None
        for frame in page.frames:
            try:
                if await frame.locator(submit_btn_selector).count() > 0:
                    target = frame
                    print(f"  [{label}] iframe 내에서 버튼 발견")
                    break
            except: continue
        
        if not target:
            # 주문이 없거나 이미 처리된 경우 모달이 안 뜰 수 있음
            print(f"  [{label}] 모달 버튼을 찾을 수 없습니다. (주문 없음 처리)")
            return {"site": label, "success": True, "totalRows": 0, "insertedCount": 0}

    # 데이터파일 생성요청 클릭
    await target.click(submit_btn_selector)
    await asyncio.sleep(1)

    # 확인 클릭
    await target.click("#lXlsReqNoticeBtnClose")
    await asyncio.sleep(1)
    print(f"PROGRESS: [{label}] 파일 생성요청 완료, 대기 중...")

    # 20~50초 새로고침하며 다운받기 버튼 대기
    DOWNLOAD_BTN = (
        "a:has-text('다운받기'), "
        "#lGrid > div > div.tui-grid-content-area.tui-grid-no-scroll-x"
        " > div.tui-grid-rside-area > div.tui-grid-body-area > div"
        " > div.tui-grid-table-container > table > tbody"
        " > tr.tui-grid-row-odd.tui-grid-cell-current-row"
        " > td:nth-child(3) > div > a"
    )

    max_attempts = max(1, config.DOMEGGOOK_WAIT_SECONDS // max(1, config.DOMEGGOOK_POLL_SECONDS))
    for i in range(max_attempts):
        await asyncio.sleep(config.DOMEGGOOK_POLL_SECONDS)
        await page.reload()
        await page.wait_for_load_state("networkidle")
        count = await page.locator(DOWNLOAD_BTN).count()
        if count > 0:
            print(f"PROGRESS: [{label}] 다운받기 버튼 발견!")
            break
        elapsed = (i + 1) * config.DOMEGGOOK_POLL_SECONDS
        print(f"PROGRESS: [{label}] 엑셀 생성 대기 중... ({elapsed}/{config.DOMEGGOOK_WAIT_SECONDS}s)")
    else:
        return {"site": label, "success": False, "error": f"엑셀 생성 시간 초과 ({config.DOMEGGOOK_WAIT_SECONDS}초)"}

    # 다운받기 클릭
    try:
        async with page.expect_download(timeout=30000) as dl:
            await page.locator(DOWNLOAD_BTN).first.click()

        download = await dl.value
        save_path = os.path.join(DOWNLOAD_DIR, download.suggested_filename)
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
