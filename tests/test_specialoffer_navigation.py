import unittest
from unittest.mock import AsyncMock, Mock

from playwright.async_api import Error as PlaywrightError

from order_worker.sites.specialoffer import (
    EXCEL_DOWNLOAD_SELECTOR,
    NAVIGATION_TIMEOUT_MS,
    find_visible_excel_button,
    goto_with_retry,
)


class SpecialofferNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_domcontentloaded_with_extended_timeout(self) -> None:
        page = AsyncMock()

        await goto_with_retry(page, "https://example.test", attempts=1)

        page.goto.assert_awaited_once_with(
            "https://example.test",
            wait_until="domcontentloaded",
            timeout=NAVIGATION_TIMEOUT_MS,
        )

    async def test_retries_transient_navigation_error(self) -> None:
        page = AsyncMock()
        page.goto.side_effect = [PlaywrightError("temporary timeout"), None]

        await goto_with_retry(page, "https://example.test", attempts=2)

        self.assertEqual(page.goto.await_count, 2)
        page.wait_for_timeout.assert_awaited_once_with(1000)

    async def test_selects_visible_button_from_responsive_duplicates(self) -> None:
        hidden = Mock()
        hidden.is_visible = AsyncMock(return_value=False)
        visible = Mock()
        visible.is_visible = AsyncMock(return_value=True)
        candidates = Mock()
        candidates.count = AsyncMock(return_value=2)
        candidates.nth.side_effect = [hidden, visible]
        page = Mock()
        page.locator.return_value = candidates

        button = await find_visible_excel_button(page)

        page.locator.assert_called_once_with(EXCEL_DOWNLOAD_SELECTOR)
        self.assertIs(button, visible)
        self.assertEqual(candidates.nth.call_count, 2)

    async def test_returns_none_when_no_excel_button_is_visible(self) -> None:
        hidden = Mock()
        hidden.is_visible = AsyncMock(return_value=False)
        candidates = Mock()
        candidates.count = AsyncMock(return_value=1)
        candidates.nth.return_value = hidden
        page = Mock()
        page.locator.return_value = candidates

        button = await find_visible_excel_button(page)

        self.assertIsNone(button)


if __name__ == "__main__":
    unittest.main()
