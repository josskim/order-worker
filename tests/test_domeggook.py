from __future__ import annotations

import unittest

from order_worker.sites.domeggook import (
    wait_for_action_target,
    wait_for_download_button,
)


class FakeLocator:
    def __init__(self, page, available_after_reloads: int = 0):
        self.page = page
        self.available_after_reloads = available_after_reloads

    async def count(self):
        return int(self.page.reload_count >= self.available_after_reloads)

    def nth(self, _index):
        return self

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True


class FakeFrame:
    def __init__(self, page, available_after_reloads: int = 0):
        self.page = page
        self.available_after_reloads = available_after_reloads

    def locator(self, _selector):
        return FakeLocator(self.page, self.available_after_reloads)


class FakePage:
    def __init__(self, available_after_reloads: int = 0):
        self.reload_count = 0
        self.available_after_reloads = available_after_reloads
        self.frames = [FakeFrame(self, available_after_reloads)]

    def locator(self, _selector):
        return FakeLocator(self, self.available_after_reloads)

    async def reload(self, **_kwargs):
        self.reload_count += 1

    async def wait_for_timeout(self, _milliseconds):
        return None


class FakeContext:
    def __init__(self, pages):
        self.pages = pages


class DomeggookWaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_download_button_waits_through_variable_generation_delay(self):
        page = FakePage(available_after_reloads=3)

        target_page, locator = await wait_for_download_button(
            page,
            "도매꾹 테스트",
            timeout_seconds=1,
            poll_seconds=0.001,
        )

        self.assertIs(target_page, page)
        self.assertIsNotNone(locator)
        self.assertEqual(page.reload_count, 3)

    async def test_action_target_checks_all_pages_and_frames(self):
        unavailable = FakePage(available_after_reloads=100)
        popup = FakePage(available_after_reloads=0)
        context = FakeContext([unavailable, popup])

        target_page, target_frame, locator = await wait_for_action_target(
            context,
            "#download",
            timeout_seconds=1,
            label="도매꾹 테스트",
        )

        self.assertIs(target_page, popup)
        self.assertIs(target_frame, popup.frames[0])
        self.assertIsNotNone(locator)

    async def test_download_button_can_appear_in_popup_frame(self):
        original = FakePage(available_after_reloads=100)
        popup = FakePage(available_after_reloads=0)
        context = FakeContext([original, popup])

        target_page, locator = await wait_for_download_button(
            original,
            "도매꾹 테스트",
            context=context,
            timeout_seconds=1,
            poll_seconds=0.001,
        )

        self.assertIs(target_page, popup)
        self.assertIsNotNone(locator)
        self.assertEqual(original.reload_count, 0)


if __name__ == "__main__":
    unittest.main()
