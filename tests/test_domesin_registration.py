from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from order_worker.sites.domesin_registration import _set_detail_html


class DomesinRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_detail_html_is_entered_after_source_button_click(self):
        page = MagicMock()
        page.wait_for_function = AsyncMock()
        page.evaluate = AsyncMock()

        source_button = MagicMock()
        source_button.wait_for = AsyncMock()
        source_button.click = AsyncMock()
        source_button_locator = MagicMock()
        source_button_locator.first = source_button

        source = MagicMock()
        source.wait_for = AsyncMock()
        source.fill = AsyncMock()
        source.input_value = AsyncMock(return_value="<p>detail</p>")

        page.locator.side_effect = lambda selector: source_button_locator if selector == ".cke_button__source, #cke_30" else source

        await _set_detail_html(page, "<p>detail</p>")

        source_button.click.assert_awaited_once()
        source.fill.assert_awaited_once_with("<p>detail</p>")
        page.evaluate.assert_awaited_once_with("() => window.CKEDITOR.instances.i_content.updateElement()")

    async def test_detail_html_rejects_empty_source(self):
        with self.assertRaisesRegex(RuntimeError, "비어"):
            await _set_detail_html(MagicMock(), "  ")


if __name__ == "__main__":
    unittest.main()
