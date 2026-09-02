from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from order_worker.sites.onchannel_registration import _set_editor_html


class OnchannelRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_editor_html_is_entered_through_source_mode(self):
        page = MagicMock()
        source_button = MagicMock()
        source_button.wait_for = AsyncMock()
        source_button.click = AsyncMock()
        page.get_by_role.return_value.first = source_button

        source_area = MagicMock()
        source_area.count = AsyncMock(return_value=0)
        source_area.wait_for = AsyncMock()
        source_area.fill = AsyncMock()
        source_area.input_value = AsyncMock(return_value="<p>detail</p>")
        page.locator.return_value.first = source_area

        await _set_editor_html(page, "<p>detail</p>")

        page.get_by_role.assert_called_once_with("button", name="Source", exact=True)
        page.locator.assert_called_once_with(".ck-editor textarea:visible")
        source_button.click.assert_awaited_once()
        source_area.fill.assert_awaited_once_with("<p>detail</p>")

    async def test_editor_html_fails_when_source_value_is_not_saved(self):
        page = MagicMock()
        source_button = MagicMock()
        source_button.wait_for = AsyncMock()
        source_button.click = AsyncMock()
        page.get_by_role.return_value.first = source_button

        source_area = MagicMock()
        source_area.count = AsyncMock(return_value=1)
        source_area.fill = AsyncMock()
        source_area.input_value = AsyncMock(return_value="")
        page.locator.return_value.first = source_area

        with self.assertRaisesRegex(RuntimeError, "Source 입력 영역"):
            await _set_editor_html(page, "<p>detail</p>")

        source_button.click.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
