"""온채널 / F온채널 주문서 자동 다운로드
경로: 로그인 > /supplier/orders.php?state=preparing > 주문내역 다운로드 클릭 > 모달에서 날짜 선택 > 체크박스 클릭 > 다운로드 클릭
"""
import asyncio
import os
from datetime import datetime, timedelta
from playwright.async_api import async_playwright
from order_worker import config
from order_worker.sites.utils import DOWNLOAD_DIR, upload_to_intranet

ACCOUNTS = [
    ("onch3",  "trustprice@naver.com", "hana2580@@", "온채널"),
    ("Fonch3", "youby74@naver.com",    "hana2580@@", "F온채널"),
]


async def dismiss_popups(page):
    """Dismiss event popups that can block the order download modal."""
    close_selectors = [
        ".layer_popup button:has-text('닫기')",
        ".layer_popup a:has-text('닫기')",
        ".layer_popup .btn-close",
        ".layer_popup [aria-label='Close']",
        ".layer_popup [onclick*='close']",
        "[id^='onch-popup'] button",
        "[id^='onch-popup'] a",
    ]

    for selector in close_selectors:
        try:
            locator = page.locator(selector)
            count = await locator.count()
            for index in range(min(count, 5)):
                try:
                    await locator.nth(index).click(timeout=1000, force=True)
                except Exception:
                    pass
        except Exception:
            pass

    await page.evaluate(
        """() => {
            document
              .querySelectorAll('.layer_popup, [id^="onch-popup"], .modal-backdrop')
              .forEach((el) => {
                el.style.display = 'none';
                el.style.visibility = 'hidden';
                el.style.pointerEvents = 'none';
              });
            document.body.style.overflow = 'auto';
        }"""
    )


async def check_agreement(page):
    await dismiss_popups(page)
    await page.evaluate(
        """() => {
            const checkbox = document.querySelector('#agreement-order-down-check');
            if (!checkbox) return;
            checkbox.checked = true;
            checkbox.dispatchEvent(new Event('input', { bubbles: true }));
            checkbox.dispatchEvent(new Event('change', { bubbles: true }));
        }"""
    )


async def run_one(site_code, user_id, password, label, page, context):
    print(f"PROGRESS: [{label}] 로그인 중...")
    await page.goto("https://www.onch3.co.kr/login/login_web.php")
    await page.wait_for_load_state("domcontentloaded")

    # 로그인 - 최신 셀렉터 (username, password, submit-btn)
    try:
        await page.fill('input[name="username"]', user_id, timeout=10000)
        await page.fill('input[name="password"]', password, timeout=10000)
        await page.click('button.submit-btn', timeout=10000)
        await page.wait_for_load_state("networkidle", timeout=30000)
        
        # 로그인 성공 여부 확인 (로그인 페이지에 머물러 있다면 실패)
        if "login_web.php" in page.url:
            return {"site": label, "success": False, "error": "로그인 실패 (아이디/비밀번호 확인 필요)"}
            
        print(f"PROGRESS: [{label}] 로그인 완료")
    except Exception as e:
        return {"site": label, "success": False, "error": f"로그인 시도 중 오류: {str(e)}"}

    # 배송준비중 주문 목록 페이지 접근
    print(f"PROGRESS: [{label}] 주문관리 페이지로 이동 중...")
    await page.goto("https://www.onch3.co.kr/supplier/orders.php?state=preparing", wait_until="networkidle")

    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
    await dismiss_popups(page)

    # 1. 주문내역 다운로드 버튼 클릭
    print(f"PROGRESS: [{label}] 주문내역 확인 중...")
    try:
        # 버튼이 보일 때까지 대기. 주문이 없으면 이 버튼이 나타나지 않음.
        excel_btn_selector = 'button.btn-excel, button:has-text("주문내역 다운로드")'
        try:
            await page.wait_for_selector(excel_btn_selector, state="visible", timeout=7000)
        except:
            # 대기 후에도 버튼이 없으면 "주문 없음"으로 간주 (0건 반환)
            print(f"PROGRESS: [{label}] 배송요청 주문이 없습니다. (0건 처리)")
            return {"site": label, "success": True, "totalRows": 0, "insertedCount": 0, "duplicateCount": 0}

        excel_btn = page.locator(excel_btn_selector).first
        await dismiss_popups(page)
        await excel_btn.click()
        
        # 엑셀 다운로드 옵션 모달창 대기
        await page.wait_for_selector("#downExcelOrderListModal", state="visible", timeout=5000)
        await dismiss_popups(page)
    except Exception as e:
        # 버튼은 발견됐으나 모달이 안 뜨는 등 상호작용 실패 시
        return {"site": label, "success": False, "error": f"주문 확인 중 오류: {str(e)}"}

    # 날짜 계산 (오늘, 30일 전)
    today = datetime.now()
    start_date = (today - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date = today.strftime("%Y-%m-%d")

    # 2. 모달창에서 날짜 선택
    print(f"PROGRESS: [{label}] 날짜 설정 중 ({start_date} ~ {end_date})...")
    # 시작 날짜
    start_selector = "#downExcelOrderListModal input[name='excel-down-start-date']"
    await page.evaluate('''(args) => { 
        const el = document.querySelector(args.sel);
        if (el) {
            el.value = args.val;
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }''', {"sel": start_selector, "val": start_date})
    # 마지막 날짜
    end_selector = "#downExcelOrderListModal input[name='excel-down-end-date']"
    await page.evaluate('''(args) => { 
        const el = document.querySelector(args.sel);
        if (el) {
            el.value = args.val;
            el.dispatchEvent(new Event('change', { bubbles: true }));
            el.dispatchEvent(new Event('input', { bubbles: true }));
        }
    }''', {"sel": end_selector, "val": end_date})

    # 3. 체크박스 클릭
    print(f"PROGRESS: [{label}] 동의 체크박스 클릭 중...")
    await check_agreement(page)

    # 4. 다운로드 클릭
    print(f"PROGRESS: [{label}] 실제 엑셀 다운로드 실행 중...")
    try:
        async with page.expect_download(timeout=30000) as dl:
            await dismiss_popups(page)
            await page.click("#btn-order-excel-down")

        download = await dl.value
        save_path = os.path.join(DOWNLOAD_DIR, download.suggested_filename or f"{site_code}_order.xlsx")
        await download.save_as(save_path)
        print(f"PROGRESS: [{label}] 다운로드 완료: {save_path}")
        result = upload_to_intranet(save_path, site_code)
        return {"site": label, **result}
    except Exception as e:
        return {"site": label, "success": False, "error": f"다운로드 과정 실패: {str(e)}"}

async def run():
    results = []
    async with async_playwright() as p:
        for site_code, user_id, password, label in ACCOUNTS:
            # headless=True 로 실행 (필요시 False 로 변경하여 디버깅 가능)
            browser = await p.chromium.launch(headless=config.HEADLESS, downloads_path=DOWNLOAD_DIR)
            context = await browser.new_context(accept_downloads=True)
            page = await context.new_page()
            try:
                r = await run_one(site_code, user_id, password, label, page, context)
                results.append(r)
            except Exception as e:
                results.append({"site": label, "success": False, "error": str(e)})
            await browser.close()
    return results
