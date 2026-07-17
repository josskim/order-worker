import unittest
from unittest.mock import AsyncMock

from playwright.async_api import Error as PlaywrightError

from order_worker.sites.specialoffer import (
    NAVIGATION_TIMEOUT_MS,
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


if __name__ == "__main__":
    unittest.main()
