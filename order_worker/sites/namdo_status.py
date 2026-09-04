from __future__ import annotations

import asyncio
import re
from typing import Any

from playwright.async_api import Locator, Page, async_playwright

from order_worker import config
from order_worker.sites.namdo_registration import MANAGEMENT_URL, SITE, SITE_CODE, _login
from order_worker.sites.status_utils import ProductNotFound, failed, normalize, option_matches, product_not_found


async def _dismiss_policy_modal(page: Page) -> None:
    mask = page.locator(".n-modal-mask:visible")
    if await mask.count():
        await mask.last.click(position={"x": 5, "y": 5}, force=True)
        await page.wait_for_timeout(250)


async def _management(page: Page) -> None:
    await page.goto(MANAGEMENT_URL, wait_until="domcontentloaded", timeout=30000)
    await page.wait_for_timeout(700)
    await _dismiss_policy_modal(page)


async def _select_product_tab(page: Page, *, soldout_only: bool) -> None:
    if soldout_only:
        tab = page.get_by_text(re.compile(r"^\s*품절 상품\s*\d+\s*$"))
        if await tab.count() == 0:
            raise RuntimeError(f"{SITE}: 품절 상품 탭을 찾지 못했습니다.")
        await tab.last.click()
        await page.wait_for_timeout(500)


async def _search(page: Page, product_code: str, *, soldout_only: bool = False) -> Locator:
    await _management(page)
    await _select_product_tab(page, soldout_only=soldout_only)
    search = page.locator('input[placeholder="검색어를 입력해주세요."]:visible').last
    if await search.count() == 0:
        raise RuntimeError(f"{SITE}: 상품 검색 입력란을 찾지 못했습니다.")
    await search.fill(product_code)
    await search.press("Enter")
    await page.wait_for_timeout(800)

    rows = page.locator("tbody tr").filter(has_text=product_code)
    exact: list[Locator] = []
    for index in range(await rows.count()):
        row = rows.nth(index)
        names = row.locator(".product-name-cell")
        if await names.count() and normalize((await names.first.inner_text()).split("_", 1)[0]) == normalize(product_code):
            exact.append(row)
    if not exact:
        raise ProductNotFound(product_code)
    if len(exact) != 1:
        raise RuntimeError(f"{SITE}: 상품코드 {product_code} 검색 결과가 {len(exact)}건이라 처리하지 않았습니다.")
    return exact[0]


async def _open_edit(page: Page, product_code: str) -> None:
    row = await _search(page, product_code)
    menu = row.get_by_role("button").last
    if await menu.count() == 0:
        raise RuntimeError(f"{SITE}: 상품 수정 메뉴를 찾지 못했습니다.")
    await menu.click()
    edit = page.get_by_text("상품 수정하기", exact=True)
    if await edit.count() != 1:
        raise RuntimeError(f"{SITE}: 상품 수정하기 메뉴를 1건으로 찾지 못했습니다.")
    await edit.click()
    await page.wait_for_url(re.compile(r"/wholesale/product/edit/\d+"), timeout=30000)
    await page.wait_for_timeout(700)


async def _find_option(page: Page, option_name: str) -> tuple[Locator, str]:
    section = page.get_by_text("옵션 상세 수정", exact=True).locator("xpath=ancestor::section[1]")
    if await section.count() != 1:
        raise RuntimeError(f"{SITE}: 옵션 상세 수정 영역을 찾지 못했습니다.")

    matches: list[tuple[Locator, str]] = []
    containers = section.locator(".option-container")
    for container_index in range(await containers.count()):
        container = containers.nth(container_index)
        color = (await container.locator(".color-box").first.inner_text()).strip()
        rows = container.locator("tr:has(td.size-box)")
        for row_index in range(await rows.count()):
            row = rows.nth(row_index)
            size = (await row.locator("td.size-box").inner_text()).strip()
            label = f"{color}/{size}"
            if option_matches(option_name, label):
                matches.append((row, label))
    if len(matches) != 1:
        raise RuntimeError(f"{SITE}: 옵션명 '{option_name}'을 1건으로 찾지 못해 처리하지 않았습니다. (일치 {len(matches)}건)")
    return matches[0]


async def _option_is_soldout(row: Locator) -> bool:
    button = row.locator("td.stock-box button")
    return "active" in (await button.get_attribute("class") or "").split()


async def _option(page: Page, product_code: str, option_name: str, preview: bool, restock: bool) -> dict[str, Any]:
    await _open_edit(page, product_code)
    row, label = await _find_option(page, option_name)
    soldout = await _option_is_soldout(row)
    wanted_soldout = not restock
    if soldout == wanted_soldout:
        return {"success": True, "alreadyProcessed": True, "matchedOption": label, "verified": True}
    if preview:
        return {"success": True, "preview": True, "matchedOption": label}

    await row.locator("td.stock-box button").click()
    save = page.get_by_role("button", name="수정하기", exact=True)
    if await save.count() != 1:
        raise RuntimeError(f"{SITE}: 상품 수정 저장 버튼을 1건으로 찾지 못했습니다.")
    await save.click()
    await page.wait_for_timeout(1200)

    await _open_edit(page, product_code)
    verified_row, verified_label = await _find_option(page, option_name)
    if await _option_is_soldout(verified_row) != wanted_soldout:
        raise RuntimeError(f"{SITE}: 옵션 저장 후 품절 상태가 반영되지 않았습니다: {verified_label}")
    return {"success": True, "matchedOption": verified_label, "verified": True}


async def _open_sale_status_modal(page: Page, row: Locator) -> Locator:
    checkbox = row.get_by_role("checkbox")
    if await checkbox.count() != 1:
        raise RuntimeError(f"{SITE}: 상품 선택 체크박스를 1건으로 찾지 못했습니다.")
    await checkbox.click()
    bulk_label = page.get_by_text("일괄 변경", exact=True).last.locator(
        "xpath=ancestor::div[contains(@class, 'n-base-selection-label')]"
    )
    if await bulk_label.count() != 1:
        raise RuntimeError(f"{SITE}: 일괄 변경 선택란을 찾지 못했습니다.")
    await bulk_label.click()
    state_change = page.get_by_text("판매 상태 변경하기", exact=True)
    if await state_change.count() != 1:
        raise RuntimeError(f"{SITE}: 판매 상태 변경하기 메뉴를 1건으로 찾지 못했습니다.")
    await state_change.click()
    modal = page.locator(".modal-overlay:visible .modal-container")
    await modal.wait_for(state="visible", timeout=10000)
    return modal


async def _product(page: Page, product_code: str, preview: bool, restock: bool) -> dict[str, Any]:
    try:
        soldout_row = await _search(page, product_code, soldout_only=True)
        is_soldout = await soldout_row.count() == 1
    except ProductNotFound:
        is_soldout = False

    wanted_soldout = not restock
    if is_soldout == wanted_soldout:
        return {"success": True, "alreadyProcessed": True, "verified": True}
    row = await _search(page, product_code)
    if preview:
        return {"success": True, "preview": True}

    modal = await _open_sale_status_modal(page, row)
    await modal.locator(f'input[name="isSoldout"][value="{1 if wanted_soldout else 0}"]').check()
    async with page.expect_response(
        lambda response: response.request.method == "PATCH" and response.url.endswith("/v2/products/is_soldout"),
        timeout=30000,
    ) as response_info:
        await modal.get_by_role("button", name="변경하기", exact=True).click()
    response = await response_info.value
    if not response.ok:
        raise RuntimeError(f"{SITE}: 상품 판매 상태 변경 API가 HTTP {response.status}로 실패했습니다.")
    await page.locator(".modal-overlay").wait_for(state="hidden", timeout=10000)
    await page.wait_for_timeout(800)

    if wanted_soldout:
        try:
            verified_row = await _search(page, product_code, soldout_only=True)
            if await verified_row.count() != 1:
                raise ProductNotFound(product_code)
        except ProductNotFound as exc:
            raise RuntimeError(f"{SITE}: 상품 저장 후 일시품절 상태를 확인하지 못했습니다.") from exc
    else:
        try:
            await _search(page, product_code, soldout_only=True)
        except ProductNotFound:
            pass
        else:
            raise RuntimeError(f"{SITE}: 상품 저장 후 판매중 상태를 확인하지 못했습니다.")
        await _search(page, product_code)
    return {"success": True, "verified": True}


async def run(action: str, product_code: str, option_name: str | None = None, preview: bool = False) -> dict[str, Any]:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=config.HEADLESS)
        page = await browser.new_page(viewport={"width": 1800, "height": 1200})
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        try:
            await _login(page)
            restock = action.endswith("restock")
            if action.startswith("option-"):
                if not option_name:
                    raise RuntimeError(f"{SITE}: 옵션 품절 처리에 옵션명이 필요합니다.")
                result = await _option(page, product_code, option_name, preview, restock)
            else:
                result = await _product(page, product_code, preview, restock)
            return {"site": SITE, "siteCode": SITE_CODE, "action": action, "productCode": product_code, **result}
        except ProductNotFound:
            return product_not_found(SITE, SITE_CODE, action, product_code)
        except Exception as exc:
            return failed(SITE, SITE_CODE, action, product_code, exc)
        finally:
            await browser.close()
