"""도매의신 주문서 자동 다운로드
경로: 로그인 > 주문확인 페이지 이동 > 전체선택 > 주문확인 클릭 > 엑셀다운 페이지 이동 > 전체선택 > 엑셀다운 클릭
"""
import asyncio
import os
from playwright.async_api import async_playwright
from order_worker import config
from order_worker.sites.utils import DOWNLOAD_DIR, upload_to_intranet

SITE_CODE = "domegod"
LABEL = "도매의신"
USER_ID = "jupraha"
PASSWORD = "hare2580@@"

async def run_one(page, context):
    print(f"PROGRESS: [{LABEL}] 로그인 중...")
    await page.goto("https://www.domesin.com/scm/login.html")
    await page.wait_for_load_state("domcontentloaded")
    
    # 로그인 정보 입력 (사용자 제공 셀렉터)
    await page.fill("body > div > form > input[type=text]:nth-child(4)", USER_ID)
    await page.fill("body > div > form > input[type=password]:nth-child(5)", PASSWORD)
    await page.click("body > div > form > button.login-btn")
    await page.wait_for_load_state("networkidle")
    print(f"PROGRESS: [{LABEL}] 로그인 완료")

    # 다이얼로그 자동 수락
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

    # 1. 주문확인 페이지 이동 및 처리
    print(f"PROGRESS: [{LABEL}] 주문확인 페이지 이동 중...")
    await page.goto("https://www.domesin.com/scm/M_order/list.html")
    await page.wait_for_load_state("networkidle")

    try:
        # 전체 체크박스 선택
        checkbox_all = "#main > table.mytable2 > tbody > tr:nth-child(1) > td:nth-child(1) > input[type=checkbox]"
        if await page.locator(checkbox_all).count() > 0:
            await page.click(checkbox_all)
            # 선택주문 주문확인 클릭
            await page.click("#main > div > input:nth-child(1)")
            await page.wait_for_load_state("networkidle")
            print(f"  [{LABEL}] 주문확인 처리 완료")
    except Exception as e:
        print(f"  [{LABEL}] 주문확인 단계 스킵 (주문 없음 추정): {str(e)}")

    # 2. 엑셀다운 페이지 이동 및 다운로드
    print(f"PROGRESS: [{LABEL}] 엑셀다운 페이지 이동 중...")
    await page.goto("https://www.domesin.com/scm/M_order/list.html?o_status=1")
    await page.wait_for_load_state("networkidle")

    try:
        # 전체 체크박스 선택 (엑셀 다운용)
        checkbox_all_xls = "#main > table.mytable2 > tbody > tr:nth-child(1) > td:nth-child(1) > input[type=checkbox]"
        if await page.locator(checkbox_all_xls).count() > 0:
            await page.click(checkbox_all_xls)
            
            # 선택주문 엑셀다운 클릭
            excel_btn = "#main > div > button"
            async with page.expect_download(timeout=30000) as dl:
                await page.click(excel_btn)
                
            download = await dl.value
            save_path = os.path.join(DOWNLOAD_DIR, download.suggested_filename or "domesin_orders.xlsx")
            await download.save_as(save_path)
            print(f"PROGRESS: [{LABEL}] 다운로드 완료: {save_path}")
            
            result = upload_to_intranet(save_path, SITE_CODE)
            return {"site": LABEL, **result}
        else:
            print(f"  [{LABEL}] 다운로드할 주문이 없습니다.")
            return {"site": LABEL, "success": True, "totalRows": 0, "insertedCount": 0}
            
    except Exception as e:
        print(f"  [{LABEL}] 엑셀 다운로드 실패: {str(e)}")
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
