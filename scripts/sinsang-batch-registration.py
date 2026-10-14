"""Bridge to the existing normal Sinsang registration engine; never generates AI images."""
from __future__ import annotations
import asyncio
import json
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root))
from sinsang_worker.config import load_config
from sinsang_worker.registration import RegistrationRunner, clean_product_name
from playwright.async_api import async_playwright


async def main():
    input_data = json.load(sys.stdin)
    request, target = input_data["request"], input_data["account"]
    config = load_config(root / "config.local.json")
    account = next(item for item in config.accounts if item.name == target["siteCode"])
    assets = target["galleryImages"]
    if not assets or len(assets) > 20 or any("/intra_image/" not in item["url"] or "1000" not in item["fileName"] for item in assets):
        raise RuntimeError("신상마켓 일반등록은 image2의 1000 대표컷 1~20장이 필요합니다.")
    job = {"product_code": request["productCode"], "registration_code": request["productCode"],
           "registration_mode": "normal", "registration_title": target["productName"],
           "product": request["sinsangProduct"], "target_accounts": [account.name],
           "max_registration_images": 20, "assets": [{"image_url": item["url"], "target_color": request["sinsangProduct"].get("p_color")} for item in assets]}
    logs = []
    def log(message):
        logs.append(message)
        print("PROGRESS:", message, flush=True)
    runner = RegistrationRunner(config, log)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=config.headless)
        async def exists():
            context = await browser.new_context(**runner.browser_runner.context_options())
            page = await context.new_page()
            try:
                await runner.browser_runner.login(page, account)
                start = len(logs)
                found = await runner.verify_registered_product(page, job["product_code"], clean_product_name(job))
                if any("재확인 실패" in message for message in logs[start:]):
                    raise RuntimeError("신상마켓 기존 상품 조회에 실패해 중복 방지를 위해 등록을 중단했습니다.")
                return found
            finally:
                await context.close()
        try:
            if await exists():
                return {"success": True, "alreadyRegistered": True, "message": f"신상마켓 기존 상품 확인: {job['product_code']}"}
            if input_data.get("preview"):
                return {"success": True, "preview": True, "message": "신상마켓 등록정보 및 기존 상품 조회 확인"}
            result = await runner.register_one(browser, account, job)
            if result.get("success") and not await exists():
                return {"success": False, "error": "신상마켓 등록 후 상품 목록에서 확인하지 못했습니다."}
            if not result.get("success"):
                result["error"] = result.get("message") or "신상마켓 등록 실패"
            return result
        finally:
            await browser.close()

try:
    result = asyncio.run(main())
except Exception as error:
    result = {"success": False, "error": str(error)}
print("BATCH_RESULT:" + json.dumps(result, ensure_ascii=False), flush=True)
