"""오너클랜 / F오너클랜 주문서 자동 다운로드"""
import asyncio
import os
from playwright.async_api import async_playwright
from order_worker import config
from order_worker.sites.utils import DOWNLOAD_DIR, upload_to_intranet

ACCOUNTS = [
    # (사이트코드, 아이디, 비밀번호, 레이블)
    ("ownerclan",  "2010019378", "hare2580@@##", "오너클랜"),
    ("Fownerclan", "2010024730", "hare2580@@##", "F오너클랜"),
]

async def run_one(site_code, user_id, password, label, page, context):
    print(f"PROGRESS: [{label}] 로그인 중...")
    await page.goto("https://ownerclan.com/vender/login.php")
    await page.wait_for_load_state("domcontentloaded")
    await page.fill('input[name="id"]', user_id)
    await page.fill('input[name="passwd"]', password)
    await page.click('input[type="submit"]')
    await page.wait_for_load_state("networkidle")

    await page.goto("https://ownerclan.com/vender/order_list.php")
    await page.wait_for_load_state("networkidle")
    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))

    target_frame = None
    for frame in page.frames:
        try:
            if await frame.locator('img[src*="btn_orderexceldown"]').count() > 0:
                target_frame = frame
                break
        except:
            pass

    if not target_frame:
        return {"site": label, "success": False, "error": "다운로드 버튼 없음"}

    async with page.expect_download(timeout=30000) as dl:
        await target_frame.locator('img[src*="btn_orderexceldown"]').first.click()

    download = await dl.value
    save_path = os.path.join(DOWNLOAD_DIR, download.suggested_filename)
    await download.save_as(save_path)
    print(f"PROGRESS: [{label}] 다운로드 완료: {save_path}")

    result = upload_to_intranet(save_path, site_code)
    return {"site": label, **result}

async def run():
    results = []
    async with async_playwright() as p:
        for site_code, user_id, password, label in ACCOUNTS:
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
