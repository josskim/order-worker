"""Wait for the confirmed category before selecting asynchronous child lists."""
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError


async def wait_category_option(page: Page, selector: str, label: str) -> None:
    try:
        await page.wait_for_function(
            r"""([selector, label]) => {
                const select = document.querySelector(selector);
                return select && Array.from(select.options).some(option =>
                    (option.textContent || '').replace(/☞/g, '').replace(/\s+/g, ' ').trim() === label
                );
            }""",
            arg=[selector, label], timeout=15000,
        )
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(f"확정한 카테고리를 사이트에서 찾지 못했습니다: {label}. 저장 목록을 확인해 주세요.") from exc
