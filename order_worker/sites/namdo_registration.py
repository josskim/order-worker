from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps
from playwright.async_api import Locator, Page, async_playwright

from order_worker import config


SITE = "남도마켓"
SITE_CODE = "namdo"
LOGIN_URL = "https://ceo.ndmarket.co.kr/wholesale/login"
MANAGEMENT_URL = "https://ceo.ndmarket.co.kr/wholesale/product"
REGISTER_URL = "https://ceo.ndmarket.co.kr/wholesale/product/create"
PRODUCT_IMAGE_SIZE = 1000
DEFAULT_WATERMARK_TEXT = "Praha Shop 조원"
WATERMARK_FONT_PATHS = (
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/noto/NotoSansKR-Regular.ttf"),
    Path("C:/Windows/Fonts/malgun.ttf"),
    Path("C:/Windows/Fonts/malgunbd.ttf"),
)


def _credentials() -> tuple[str, str]:
    user_id = os.getenv("NAMDO_USER_ID", "").strip()
    password = os.getenv("NAMDO_PASSWORD", "")
    if not user_id or not password:
        raise RuntimeError("남도마켓 로그인 환경변수(NAMDO_USER_ID/NAMDO_PASSWORD)가 없습니다.")
    return user_id, password


def _watermark_font(size: int) -> ImageFont.FreeTypeFont:
    configured = os.getenv("NAMDO_WATERMARK_FONT", "").strip()
    candidates = ([Path(configured)] if configured else []) + list(WATERMARK_FONT_PATHS)
    for path in candidates:
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise RuntimeError("남도마켓 워터마크에 사용할 한글 글꼴을 찾지 못했습니다.")


def _apply_repeated_watermark(image: Image.Image, text: str = DEFAULT_WATERMARK_TEXT) -> Image.Image:
    """Overlay a light diagonal repeating watermark while preserving image dimensions."""
    clean_text = text.strip()
    if not clean_text:
        return image.convert("RGB")
    base = image.convert("RGBA")
    font = _watermark_font(max(28, round(min(base.size) * 0.045)))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = probe.textbbox((0, 0), clean_text, font=font)
    label = Image.new("RGBA", (right - left + 48, bottom - top + 32), (0, 0, 0, 0))
    label_draw = ImageDraw.Draw(label)
    label_draw.text((26 - left, 17 - top), clean_text, font=font, fill=(235, 235, 235, 96))
    diagonal = label.rotate(35, expand=True, resample=Image.Resampling.BICUBIC)

    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    step_x = max(240, diagonal.width + 20)
    step_y = max(150, diagonal.height + 10)
    row = 0
    for y in range(-diagonal.height, base.height + diagonal.height, step_y):
        offset = -(step_x // 2) if row % 2 else 0
        for x in range(-diagonal.width + offset, base.width + diagonal.width, step_x):
            overlay.alpha_composite(diagonal, (x, y))
        row += 1
    return Image.alpha_composite(base, overlay).convert("RGB")


def _normalize_product_image(content: bytes, target: Path, watermark_text: str = "") -> None:
    """Fit an uploaded product image into Namdo's square image format without cropping."""
    with Image.open(BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail((PRODUCT_IMAGE_SIZE, PRODUCT_IMAGE_SIZE), Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", (PRODUCT_IMAGE_SIZE, PRODUCT_IMAGE_SIZE), "white")
        canvas.paste(
            image,
            ((PRODUCT_IMAGE_SIZE - image.width) // 2, (PRODUCT_IMAGE_SIZE - image.height) // 2),
        )
        if watermark_text:
            canvas = _apply_repeated_watermark(canvas, watermark_text)
        canvas.save(target, format="JPEG", quality=95, optimize=True)


def _save_watermarked_content_image(content: bytes, target: Path, watermark_text: str) -> None:
    with Image.open(BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        if watermark_text:
            image = _apply_repeated_watermark(image, watermark_text)
        image.save(target, format="JPEG", quality=95, optimize=True)


def _download_images(account: dict[str, Any], namdo: dict[str, Any], target_dir: Path) -> tuple[list[Path], Path]:
    max_images = min(20, max(1, int(namdo.get("maxProductImages") or 20)))
    watermark = namdo.get("watermark") or {}
    watermark_text = str(watermark.get("text") or DEFAULT_WATERMARK_TEXT).strip() if watermark.get("enabled", True) else ""
    items = account.get("galleryImages") or [account["mainImage"], *account.get("additionalImages", [])]
    product_paths: list[Path] = []
    for index, item in enumerate(items[:max_images]):
        file_name = Path(str(item.get("fileName") or f"image-{index + 1}.jpg")).stem
        target = target_dir / f"product-{index + 1:02d}-{file_name}.jpg"
        response = requests.get(str(item["url"]), timeout=45)
        response.raise_for_status()
        _normalize_product_image(response.content, target, watermark_text)
        product_paths.append(target)
    if not product_paths:
        raise RuntimeError(f"{SITE}에 등록할 상품이미지가 없습니다.")

    content_item = namdo.get("contentImage") or account.get("mainImage")
    if not content_item or not content_item.get("url"):
        raise RuntimeError(f"{SITE} 상세 이미지로 사용할 메인컷이 없습니다.")
    content_name = Path(str(content_item.get("fileName") or "content.jpg")).stem
    content_path = target_dir / f"content-{content_name}.jpg"
    response = requests.get(str(content_item["url"]), timeout=45)
    response.raise_for_status()
    _save_watermarked_content_image(response.content, content_path, watermark_text)
    return product_paths, content_path


async def _dismiss_optional_button(page: Page, label: str) -> bool:
    button = page.get_by_role("button", name=label, exact=True)
    if await button.count() and await button.first.is_visible():
        await button.first.click()
        await page.wait_for_timeout(300)
        return True
    return False


async def _login(page: Page) -> None:
    user_id, password = _credentials()
    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    if "/wholesale/login" not in page.url:
        return
    await page.get_by_placeholder("이메일", exact=True).fill(user_id)
    await page.get_by_placeholder("비밀번호", exact=True).fill(password)
    await page.get_by_role("button", name="로그인", exact=True).click()
    await page.wait_for_url(re.compile(r"/wholesale/(?!login)"), timeout=30000)
    await page.wait_for_timeout(700)
    await _dismiss_optional_button(page, "다음에 하기")


async def _already_registered(page: Page, product_code: str) -> bool:
    await page.goto(MANAGEMENT_URL, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(700)
    await _dismiss_optional_button(page, "다음에 하기")
    search = page.locator('input[placeholder="검색어를 입력해주세요."]:visible').last
    if await search.count():
        await search.fill(product_code)
        await search.press("Enter")
        await page.wait_for_timeout(1000)
    return await page.get_by_text(product_code, exact=False).count() > 0


async def _click_last_exact(scope: Page | Locator, text: str) -> None:
    matches = scope.get_by_text(re.compile(rf"^\s*{re.escape(text)}\s*$"))
    visible: list[Locator] = []
    for index in range(await matches.count()):
        item = matches.nth(index)
        if await item.is_visible():
            visible.append(item)
    if not visible:
        raise RuntimeError(f"{SITE} 선택값을 찾지 못했습니다: {text}")
    await visible[-1].click()
    await asyncio.sleep(0.25)


async def _select_category(page: Page, path: list[str]) -> None:
    category = page.locator("section#category")
    for label in path:
        await _click_last_exact(category, label)
    selected = category.locator(".tag-box").filter(has_text=path[-1])
    if not await selected.count():
        raise RuntimeError(f"{SITE} 카테고리가 선택되지 않았습니다: {' > '.join(path)}")


async def _select_colors(page: Page, colors: list[str]) -> None:
    section = page.locator("section#color")
    add_input = page.get_by_placeholder("색상을 등록 후 아래 색상 목록에서 선택 해주세요.", exact=True)
    search = page.get_by_placeholder("색상을 검색해 보세요.", exact=True)
    for color in colors:
        await add_input.fill(color)
        await add_input.press("Enter")
        await page.wait_for_timeout(250)
        await search.fill(color)
        await page.wait_for_timeout(250)
        await _click_last_exact(section, color)
    await search.fill("")


async def _select_sizes(page: Page, sizes: list[str]) -> None:
    section = page.locator("section#size")
    search = page.get_by_placeholder("사이즈를 검색해 보세요.", exact=True)
    custom = page.get_by_placeholder("나만의 사이즈를 등록할 수 있습니다.", exact=True)
    for size in sizes:
        await search.fill(size)
        await page.wait_for_timeout(300)
        matches = section.get_by_text(re.compile(rf"^\s*{re.escape(size)}\s*$", re.IGNORECASE))
        visible = [matches.nth(index) for index in range(await matches.count()) if await matches.nth(index).is_visible()]
        if not visible:
            await custom.fill(size)
            await custom.press("Enter")
            await page.wait_for_timeout(700)
            await search.fill(size)
            await page.wait_for_timeout(300)
            matches = section.get_by_text(re.compile(rf"^\s*{re.escape(size)}\s*$", re.IGNORECASE))
            visible = [matches.nth(index) for index in range(await matches.count()) if await matches.nth(index).is_visible()]
        if not visible:
            raise RuntimeError(f"{SITE} 사이즈를 찾거나 등록하지 못했습니다: {size}")
        await visible[-1].click()
        await page.wait_for_timeout(250)
    await search.fill("")


async def _select_material(page: Page, material: str) -> None:
    section = page.locator("section#materials")
    search = page.get_by_placeholder("소재를 검색해 보세요.", exact=True)
    await search.fill(material)
    await page.wait_for_timeout(300)
    await _click_last_exact(section, material)
    await search.fill("")


async def _fill_tags(page: Page, tags: list[str]) -> None:
    field = page.get_by_placeholder("태그를 입력 후 엔터를 치면 등록이 됩니다.", exact=True)
    for tag in tags[:10]:
        await field.fill(tag)
        await field.press("Enter")
        await page.wait_for_timeout(120)


async def _fill_form(
    page: Page,
    request: dict[str, Any],
    account: dict[str, Any],
    product_images: list[Path],
    content_image: Path,
) -> None:
    namdo = request.get("namdo") or {}
    await page.goto(REGISTER_URL, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(900)
    await _dismiss_optional_button(page, "다음에 하기")
    if not await page.get_by_role("button", name="등록하기", exact=True).count():
        raise RuntimeError(f"{SITE} 상품등록 화면에 접근하지 못했습니다: {page.url}")

    file_inputs = page.locator('input[type="file"]')
    # 첫 번째 file input은 좌측 업체 프로필 이미지이며 상품 폼과 무관하다.
    if await file_inputs.count() < 3:
        raise RuntimeError(f"{SITE} 상품/상세 이미지 입력란을 찾지 못했습니다.")
    await file_inputs.nth(1).set_input_files([str(path) for path in product_images])
    await page.wait_for_timeout(1000)

    await page.get_by_placeholder("상품명 입력 해주세요", exact=True).fill(str(account["productName"]))
    await page.get_by_placeholder("관리 코드를 입력해주세요.", exact=True).fill(str(account["code"]))
    await _select_category(page, [str(value) for value in namdo.get("categoryPath") or ["여성의류"]])
    await _select_colors(page, [str(value) for value in request.get("colors", []) if str(value).strip()])
    await _select_sizes(page, [str(value) for value in request.get("sizes", []) if str(value).strip()])
    await page.get_by_placeholder("판매 가격을 입력해주세요.", exact=True).fill(str(account["supplyPrice"]))
    await _select_material(page, str(namdo.get("material") or "폴리에스테르"))
    country = str(namdo.get("country") or "중국")
    await page.locator("label.country-list").filter(has_text=re.compile(rf"^\s*{re.escape(country)}\s*$")).click()
    await page.get_by_placeholder("상품설명을 입력해주세요. 상품 상태와 특징을 자세히 작성해 주세요.", exact=False).fill(
        str(namdo.get("description") or "")
    )
    await file_inputs.nth(2).set_input_files(str(content_image))
    await page.wait_for_timeout(500)
    await _fill_tags(page, [str(value) for value in request.get("keywordItems", []) if str(value).strip()])
    await page.get_by_text(str(namdo.get("displayType") or "전체공개"), exact=True).last.click()

    selected_options = page.locator(".price-detail-list, .option-detail-list, .option-table").filter(has_text=str(account["supplyPrice"]))
    if not await selected_options.count():
        option_text = await page.locator("body").inner_text()
        if not all(value.casefold() in option_text.casefold() for value in [*request.get("colors", []), *request.get("sizes", [])]):
            raise RuntimeError(f"{SITE} 색상/사이즈 옵션 조합이 생성되지 않았습니다.")
    product_cards = page.locator("section#image .n-upload-file--image-card-type")
    if await product_cards.count() != len(product_images):
        raise RuntimeError(
            f"{SITE} 상품이미지 첨부 검증 실패: 예상 {len(product_images)}장, 실제 {await product_cards.count()}장"
        )
    content_section = page.locator("section").filter(
        has=page.get_by_role("heading", name="상세 이미지 등록", exact=True)
    ).first
    if await content_section.locator(".n-upload-file--image-card-type").count() != 1:
        raise RuntimeError(f"{SITE} 상세 이미지가 첨부되지 않았습니다.")


async def run_account(request: dict[str, Any], account_payload: dict[str, Any], preview: bool = False) -> dict[str, Any]:
    product_code = str(account_payload.get("code") or "")
    work_dir = Path(tempfile.mkdtemp(prefix="namdo-register-", dir=config.DOWNLOAD_DIR))
    try:
        product_images, content_image = _download_images(account_payload, request.get("namdo") or {}, work_dir)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=config.HEADLESS)
            context = await browser.new_context(viewport={"width": 1800, "height": 1200})
            page = await context.new_page()
            try:
                await _login(page)
                if await _already_registered(page, product_code):
                    return {"site": SITE, "siteCode": SITE_CODE, "success": True, "alreadyRegistered": True, "productCode": product_code, "message": f"이미 등록된 상품입니다: {product_code}"}
                await _fill_form(page, request, account_payload, product_images, content_image)
                if preview:
                    return {"site": SITE, "siteCode": SITE_CODE, "success": True, "preview": True, "productCode": product_code, "message": "남도마켓 필수값 자동입력 검증 완료(등록 전 중단)"}

                await page.get_by_role("button", name="등록하기", exact=True).click()
                await page.wait_for_url(re.compile(r"/wholesale/product(?:\?.*)?$"), timeout=120000)
                await page.wait_for_timeout(1200)
                if await _already_registered(page, product_code):
                    return {"site": SITE, "siteCode": SITE_CODE, "success": True, "productCode": product_code, "message": f"상품등록 완료: {product_code}"}
                raise RuntimeError(f"{SITE} 등록 후 상품관리에서 관리코드를 찾지 못했습니다.")
            finally:
                await browser.close()
    except Exception as exc:
        return {"site": SITE, "siteCode": SITE_CODE, "success": False, "productCode": product_code, "error": str(exc)[:1600]}
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
