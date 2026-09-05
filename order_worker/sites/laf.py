from __future__ import annotations

import asyncio
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import requests
from playwright.async_api import Browser, Page, async_playwright

from order_worker import config


SITE = "라프"
SITE_CODE = "cafe_laf"


def _write_url() -> str:
    return f"https://cafe.naver.com/ca-fe/cafes/{config.LAF_CAFE_ID}/articles/write?boardType=L"


def _article_id(article_url: str | None) -> str:
    value = article_url or ""
    match = re.search(r"(?:/articles/|/liveprice/)(\d+)", value)
    if not match:
        match = re.search(r"articleid(?:%3D|=)(\d+)", value, re.IGNORECASE)
    if not match:
        raise RuntimeError("라프 게시글 주소가 없어 수정할 수 없습니다. 먼저 라프 상품등록을 진행해 주세요.")
    return match.group(1)


def _chrome_executable() -> Path:
    candidates = [
        os.getenv("CHROME_PATH", ""),
        str(Path(os.getenv("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(os.getenv("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
        str(Path(os.getenv("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise RuntimeError("라프 전용 Chrome 실행 파일을 찾지 못했습니다.")


def _chrome_ready() -> bool:
    try:
        return requests.get(f"http://127.0.0.1:{config.LAF_CHROME_DEBUG_PORT}/json/version", timeout=1).ok
    except requests.RequestException:
        return False


async def _ensure_chrome(start_url: str) -> None:
    if _chrome_ready():
        return
    config.LAF_CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    subprocess.Popen(
        [
            str(_chrome_executable()),
            f"--remote-debugging-port={config.LAF_CHROME_DEBUG_PORT}",
            f"--user-data-dir={config.LAF_CHROME_PROFILE_DIR}",
            "--no-first-run",
            "--no-default-browser-check",
            start_url,
        ],
        creationflags=flags,
        close_fds=True,
    )
    for _ in range(30):
        await asyncio.sleep(0.5)
        if _chrome_ready():
            return
    raise RuntimeError("라프 전용 Chrome 연결 포트가 열리지 않았습니다.")


async def _page_for(browser: Browser, target_url: str) -> Page:
    contexts = browser.contexts
    if not contexts:
        raise RuntimeError("라프 전용 Chrome 프로필을 열지 못했습니다.")
    context = contexts[0]
    page = next((item for item in context.pages if "cafe.naver.com" in item.url), None) or await context.new_page()
    await page.goto(target_url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(1200)
    if "nid.naver.com" in page.url or "nidlogin" in page.url:
        raise RuntimeError("라프 전용 Chrome에서 네이버 로그인이 필요합니다. 로그인 후 다시 실행해 주세요.")
    return page


async def _select_sale_board(page: Page) -> None:
    await page.locator("button.button").first.wait_for(state="visible", timeout=30_000)
    await page.locator("button.button").first.click()
    sale = page.locator("button.option").filter(has_text="♥ Sale").first
    await sale.wait_for(state="visible", timeout=10_000)
    await sale.click()
    await page.locator(".se-text-paragraph").filter(has_text="♥ 상품명").first.wait_for(
        state="visible",
        timeout=30_000,
    )


async def _replace_paragraph(page: Page, marker: str, value: str) -> None:
    paragraph = page.locator(".se-text-paragraph").filter(has_text=marker).first
    if await paragraph.count() == 0:
        raise RuntimeError(f"라프 기본 글양식에서 '{marker}' 항목을 찾지 못했습니다.")
    await page.keyboard.press("Escape")
    await paragraph.scroll_into_view_if_needed()
    # First click activates the SmartEditor text component. Then drag across the
    # rendered text nodes so the editor's own selection model receives the edit.
    await paragraph.click()
    await page.wait_for_timeout(100)
    spans = paragraph.locator("span")
    first_box = await spans.first.bounding_box()
    last_box = await spans.last.bounding_box()
    if not first_box or not last_box:
        raise RuntimeError(f"라프 글양식의 '{marker}' 텍스트 영역을 선택하지 못했습니다.")
    await page.mouse.move(last_box["x"] + last_box["width"] - 1, last_box["y"] + last_box["height"] / 2)
    await page.mouse.down()
    await page.mouse.move(first_box["x"] + 1, first_box["y"] + first_box["height"] / 2, steps=12)
    await page.mouse.up()
    await page.keyboard.insert_text(value)
    await page.wait_for_timeout(400)


def _order_url(product_code: str) -> str:
    return f"https://chowon.prahashop.shop/cafe?p_num={product_code}"


async def _replace_order_link_card(page: Page, product_code: str) -> None:
    url = _order_url(product_code)
    existing_card = page.locator(".se-component.se-oglink").filter(has_text="chowon.prahashop.shop").first
    if await existing_card.count():
        return

    paragraph = page.locator(".se-text-paragraph").filter(
        has_text="chowon.prahashop.shop/cafe?p_num="
    ).first
    if await paragraph.count() == 0:
        raise RuntimeError("라프 기본 글양식에서 주문 링크 위치를 찾지 못했습니다.")

    await paragraph.scroll_into_view_if_needed()
    await paragraph.click()
    await page.wait_for_timeout(100)
    spans = paragraph.locator("span")
    first_box = await spans.first.bounding_box()
    last_box = await spans.last.bounding_box()
    if not first_box or not last_box:
        raise RuntimeError("라프 주문 링크 텍스트 영역을 선택하지 못했습니다.")
    await page.mouse.move(last_box["x"] + last_box["width"] - 1, last_box["y"] + last_box["height"] / 2)
    await page.mouse.down()
    await page.mouse.move(first_box["x"] + 1, first_box["y"] + first_box["height"] / 2, steps=12)
    await page.mouse.up()
    await page.keyboard.press("Backspace")

    card_count = await page.locator(".se-component.se-oglink").count()
    await page.locator("button[data-name='oglink']").click()
    popup = page.locator(".se-popup-oglink:visible")
    await popup.wait_for(state="visible", timeout=10_000)
    await popup.locator(".se-popup-oglink-input").fill(url)
    await popup.locator(".se-popup-oglink-button").click()
    confirm = popup.locator(".se-popup-button-confirm")
    for _ in range(60):
        if await confirm.is_enabled():
            break
        await page.wait_for_timeout(500)
    else:
        raise RuntimeError("라프 주문 링크 미리보기를 불러오지 못했습니다.")
    await confirm.click()
    await page.wait_for_function(
        """expected => document.querySelectorAll('.se-component.se-oglink').length > expected""",
        arg=card_count,
        timeout=10_000,
    )


async def _place_after_paragraph(page: Page, marker: str) -> None:
    paragraph = page.locator(".se-text-paragraph").filter(has_text=marker).first
    if await paragraph.count() == 0:
        raise RuntimeError(f"라프 기본 글양식에서 '{marker}' 위치를 찾지 못했습니다.")
    await paragraph.scroll_into_view_if_needed()
    await paragraph.click()
    await paragraph.evaluate(
        """element => {
          const range = document.createRange();
          range.selectNodeContents(element);
          range.collapse(false);
          const selection = window.getSelection();
          selection.removeAllRanges();
          selection.addRange(range);
        }"""
    )
    await page.keyboard.press("Enter")


def _download_images(images: list[dict[str, Any]], target_dir: Path) -> list[Path]:
    files: list[Path] = []
    for index, image in enumerate(images):
        url = str(image.get("url") or "")
        response = requests.get(url, timeout=45)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        extension = ".png" if "png" in content_type else ".webp" if "webp" in content_type else ".jpg"
        target = target_dir / f"{index + 1:02d}{extension}"
        target.write_bytes(response.content)
        files.append(target)
    return files


async def _upload_images(page: Page, files: list[Path]) -> None:
    if not files:
        raise RuntimeError("라프에 등록할 이미지가 없습니다.")
    before = await page.locator(".se-component.se-image img.se-image-resource").count()
    async with page.expect_file_chooser(timeout=15_000) as chooser_info:
        await page.locator("button[data-name='image']").click()
    await (await chooser_info.value).set_files([str(file) for file in files])
    individual = page.get_by_text("개별사진", exact=True)
    if await individual.is_visible(timeout=3000):
        await individual.click()
    expected = before + len(files)
    await page.wait_for_function(
        """expected => {
          const images = Array.from(document.querySelectorAll('.se-component.se-image img.se-image-resource'));
          return images.length >= expected && images.every(image => image.complete && image.naturalWidth > 0);
        }""",
        arg=expected,
        timeout=180_000,
    )


async def _fill_product_fields(page: Page, account: dict[str, Any]) -> None:
    await page.locator("textarea.textarea_input").fill(str(account.get("productName") or ""))
    await _replace_paragraph(page, "♥ 상품명", f"♥ 상품명 : {account.get('productName') or ''}")
    await _replace_paragraph(page, "♥ 현금가", f"♥ 현금가 : {int(account.get('supplyPrice') or 0):,} 원")
    await _replace_paragraph(page, "♥ 색상", f"♥ 색상 : {account.get('color') or '-'}")
    await _replace_paragraph(page, "♥ 사이즈", f"♥ 사이즈 : {str(account.get('size') or 'FREE').upper()}")
    await _replace_paragraph(page, "♥ 배송비", f"♥ 배송비 : {int(account.get('deliveryFee') or 3000):,}원")
    await _replace_order_link_card(page, str(account.get("code") or ""))


async def _publish(page: Page) -> str:
    notice = page.locator("#notice")
    if await notice.count() and not await notice.is_checked():
        await page.locator("label[for='notice']").click()
    register = page.get_by_role("button", name="등록", exact=True).last
    if await register.count() == 0:
        raise RuntimeError("라프 글 등록 버튼을 찾지 못했습니다.")
    page.once("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
    await register.click()
    try:
        await page.wait_for_url(
            re.compile(
                r"^(?!.*?/modify(?:\?|$)).*(?:/articles/|/liveprice/|articleid(?:%3D|=))\d+",
                re.IGNORECASE,
            ),
            timeout=30_000,
        )
    except Exception:
        await page.wait_for_timeout(1500)
    article_id = _article_id(page.url)
    return f"https://cafe.naver.com/{config.LAF_CAFE_SLUG}/{article_id}"


async def run_registration(request: dict[str, Any], account: dict[str, Any], preview: bool = False) -> dict[str, Any]:
    if preview:
        return {"site": SITE, "siteCode": SITE_CODE, "productCode": str(account.get("code") or ""), "success": True, "preview": True}
    images = account.get("galleryImages") if isinstance(account.get("galleryImages"), list) else []
    work_dir = Path(tempfile.mkdtemp(prefix="laf-register-", dir=config.DOWNLOAD_DIR))
    try:
        files = await asyncio.to_thread(_download_images, images, work_dir)
        await _ensure_chrome(_write_url())
        async with async_playwright() as playwright:
            browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{config.LAF_CHROME_DEBUG_PORT}")
            page = await _page_for(browser, _write_url())
            await _select_sale_board(page)
            await _fill_product_fields(page, account)
            await _place_after_paragraph(page, "농협 302-0879-0807-91")
            await _upload_images(page, files)
            article_url = await _publish(page)
            return {
                "site": SITE,
                "siteCode": SITE_CODE,
                "productCode": str(account.get("code") or ""),
                "success": True,
                "verified": True,
                "articleUrl": article_url,
                "imageCount": len(files),
                "message": f"상품등록 완료: 이미지 {len(files)}장",
            }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


async def run_edit(
    browser: Browser | None,
    site_code: str,
    product_code: str,
    changes: dict[str, Any],
    preview: bool,
    *,
    article_url: str | None = None,
) -> dict[str, Any]:
    article_id = _article_id(article_url)
    title_sites = {str(value) for value in changes.get("titleSites", [])}
    prices = changes.get("prices") if isinstance(changes.get("prices"), dict) else {}
    title = str(changes.get("title") or "").strip() if site_code in title_sites else ""
    price = int(prices[site_code]) if prices.get(site_code) is not None else None
    applied = [value for value, enabled in (("상품명", bool(title)), ("현금가", price is not None)) if enabled]
    if preview:
        return {"success": True, "preview": True, "message": f"수정 예정: {', '.join(applied)}"}
    await _ensure_chrome(article_url or _write_url())
    async with async_playwright() as playwright:
        cdp_browser = await playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{config.LAF_CHROME_DEBUG_PORT}")
        edit_url = f"https://cafe.naver.com/ca-fe/cafes/{config.LAF_CAFE_ID}/articles/{article_id}/modify?boardType=L"
        page = await _page_for(cdp_browser, edit_url)
        await page.locator("textarea.textarea_input").wait_for(state="visible", timeout=30_000)
        if title:
            await page.locator("textarea.textarea_input").fill(title)
            await _replace_paragraph(page, "♥ 상품명", f"♥ 상품명 : {title}")
        if price is not None:
            await _replace_paragraph(page, "♥ 현금가", f"♥ 현금가 : {price:,} 원")
        saved_url = await _publish(page)
        return {
            "success": True,
            "verified": True,
            "articleUrl": saved_url,
            "message": f"상품 수정 완료: {', '.join(applied)}",
        }
