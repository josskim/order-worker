from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from order_worker.sites.domesin_registration import _product_name, _select_text, _set_detail_html


class DomesinRegistrationTests(unittest.IsolatedAsyncioTestCase):
    def test_product_name_removes_brackets_but_preserves_contents(self):
        self.assertEqual(_product_name("G126956_[끈팬티]심플 시스루레이스"), "G126956 끈팬티심플 시스루레이스")
        self.assertEqual(_product_name("G1_[가][나]"), "G1 가나")

    async def test_detail_html_is_entered_after_source_button_click(self):
        page = MagicMock()
        page.wait_for_function = AsyncMock()
        page.wait_for_timeout = AsyncMock()
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

    async def test_select_text_waits_for_ajax_option_and_rechecks_options(self):
        page = MagicMock()
        page.wait_for_function = AsyncMock()
        page.wait_for_timeout = AsyncMock()

        select = MagicMock()
        option_locator = MagicMock()
        option_locator.evaluate_all = AsyncMock(
            side_effect=[
                [],
                [{"value": "women", "text": "여성의류"}],
            ]
        )
        select.locator.return_value = option_locator
        select.select_option = AsyncMock()

        page.locator.return_value.first = select

        await _select_text(page, 'select[name="cate2"]', "여성의류")

        page.wait_for_function.assert_awaited_once()
        self.assertEqual(page.wait_for_function.await_args.kwargs["arg"], ['select[name="cate2"]', "여성의류"])
        self.assertEqual(page.wait_for_function.await_args.kwargs["timeout"], 12000)
        select.select_option.assert_awaited_once_with("women")

    async def test_select_text_reports_missing_delayed_option_clearly(self):
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError

        page = MagicMock()
        page.wait_for_function = AsyncMock(side_effect=PlaywrightTimeoutError("timeout"))
        page.wait_for_timeout = AsyncMock()

        select = MagicMock()
        option_locator = MagicMock()
        option_locator.evaluate_all = AsyncMock(return_value=[])
        select.locator.return_value = option_locator
        page.locator.return_value.first = select

        with self.assertRaisesRegex(RuntimeError, "여성의류"):
            await _select_text(page, 'select[name="cate2"]', "여성의류")

    async def test_detail_html_rejects_empty_source(self):
        with self.assertRaisesRegex(RuntimeError, "비어"):
            await _set_detail_html(MagicMock(), "  ")


if __name__ == "__main__":
    unittest.main()
