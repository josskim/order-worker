from __future__ import annotations

import asyncio
from pathlib import Path

from playwright.async_api import async_playwright

from order_worker import config
from order_worker.sites.domeggook import (
    ACCOUNTS,
    wait_for_download_button,
)


async def main() -> None:
    site_code, user_id, password, label = ACCOUNTS[0]
    config.ensure_directories()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=config.HEADLESS)
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()
        try:
            print(f"[{label}] 로그인 페이지 이동", flush=True)
            await page.goto(
                "https://domeggook.com/ssl/member/mem_loginForm.php",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            await page.fill("#idInput", user_id)
            await page.fill("#pwInput", password)
            await page.click("#formLogin > input.formSubmit")
            await page.wait_for_load_state("domcontentloaded")

            print(f"[{label}] 상품공급사센터 이동", flush=True)
            await page.click("#rightMenu > li:nth-child(6) > a")
            await page.wait_for_load_state("domcontentloaded")
            print(f"[{label}] 발주·발송 이동", flush=True)
            await page.click(
                "#orderStatusZone > div.pContent > div.halfZone.pLeft > ul > li:nth-child(2)"
            )
            await page.wait_for_load_state("domcontentloaded")

            print(f"[{label}] 엑셀 다운로드 관리 이동", flush=True)
            await page.goto(
                "https://domeggook.com/sc/excel/getOrderList",
                wait_until="domcontentloaded",
                timeout=60000,
            )

            print(f"[{label}] 최신 생성 파일 찾기", flush=True)
            download_page, download_button = await wait_for_download_button(
                page,
                label,
                context=context,
                timeout_seconds=15,
                poll_seconds=1,
            )
            async with download_page.expect_download(
                timeout=config.DOMEGGOOK_DOWNLOAD_TIMEOUT_SECONDS * 1000
            ) as download_info:
                await download_button.click()

            download = await download_info.value
            save_path = Path(config.DOWNLOAD_DIR) / (
                download.suggested_filename or f"{site_code}_latest.xlsx"
            )
            await download.save_as(save_path)
            print(save_path.resolve(), flush=True)
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
