from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from order_worker.sites.domeggook import (
    download_row_timestamp,
    latest_visible_download,
    wait_for_action_target,
    wait_for_download_button,
)

KST = timezone(timedelta(hours=9), name="KST")


class FakeRow:
    def __init__(self, text):
        self.text = text

    async def inner_text(self):
        return self.text


class FakeDownloadCandidate:
    def __init__(self, row_text):
        self.row_text = row_text

    def locator(self, _selector):
        return FakeRow(self.row_text)


class FakeLocator:
    def __init__(
        self,
        page,
        available_after_reloads: int = 0,
        row_times=None,
        selected_index: int | None = None,
    ):
        self.page = page
        self.available_after_reloads = available_after_reloads
        self.row_times = row_times or [None]
        self.selected_index = selected_index

    async def count(self):
        if self.page.reload_count < self.available_after_reloads:
            return 0
        return len(self.row_times)

    def nth(self, index):
        return FakeLocator(
            self.page,
            self.available_after_reloads,
            self.row_times,
            selected_index=index,
        )

    async def is_visible(self):
        return True

    async def is_enabled(self):
        return True

    def locator(self, _selector):
        index = self.selected_index or 0
        row_time = self.row_times[index]
        text = f"파일 생성 완료 다운받기 {row_time}" if row_time else "다운받기"
        return FakeRow(text)


class FakeFrame:
    def __init__(self, page, available_after_reloads: int = 0):
        self.page = page
        self.available_after_reloads = available_after_reloads

    def locator(self, _selector):
        return FakeLocator(
            self.page,
            self.available_after_reloads,
            self.page.row_times,
        )


class FakePage:
    def __init__(self, available_after_reloads: int = 0, row_times=None):
        self.reload_count = 0
        self.available_after_reloads = available_after_reloads
        self.row_times = row_times or [None]
        self.frames = [FakeFrame(self, available_after_reloads)]

    def locator(self, _selector):
        return FakeLocator(
            self,
            self.available_after_reloads,
            self.row_times,
        )

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

    async def test_latest_generated_file_is_selected_instead_of_first_button(self):
        page = FakePage(
            row_times=[
                "2026-07-24 08:30:00",
                "2026-07-25 09:17:45",
                "2026-07-23 17:10:00",
            ]
        )

        selected_time, locator = await latest_visible_download(
            page.locator("a:has-text('다운받기')")
        )

        self.assertEqual(
            selected_time,
            datetime(2026, 7, 25, 9, 17, 45, tzinfo=KST),
        )
        self.assertEqual(locator.selected_index, 1)

    async def test_old_download_is_rejected_while_waiting_for_new_request(self):
        page = FakePage(row_times=["2026-07-24 09:17:45"])

        selected = await latest_visible_download(
            page.locator("a:has-text('다운받기')"),
            not_before=datetime(2026, 7, 25, 9, 17, 0, tzinfo=KST),
        )

        self.assertIsNone(selected)

    async def test_request_time_is_used_instead_of_later_processing_time(self):
        timestamp = await download_row_timestamp(
            FakeDownloadCandidate(
                "요청일시 2026-07-25 09:17:45 "
                "처리일시 2026-07-25 09:23:01"
            )
        )

        self.assertEqual(
            timestamp,
            datetime(2026, 7, 25, 9, 17, 45, tzinfo=KST),
        )


if __name__ == "__main__":
    unittest.main()
