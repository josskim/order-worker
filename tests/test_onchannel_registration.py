from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from order_worker.sites.onchannel_registration import _set_editor_html, _contains_product_code, _matching_product_row, _download_images


class OnchannelRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_detail_gallery_is_rejected_before_upload(self):
        payload = {"galleryImages": [
            {"fileName": "G1_1000_1.jpg", "url": "https://image.prahashop.shop/intra_image/G1/G1_1000_1.jpg"},
            {"fileName": "G1_1.jpg", "url": "https://image.prahashop.shop/intra_product/G1/G1_1.jpg"},
        ]}
        with self.assertRaisesRegex(RuntimeError, "image2"):
            _download_images(payload, Path("."))

    async def test_product_code_requires_exact_boundary(self):
        self.assertTrue(_contains_product_code("G127154_상품명", "G127154"))
        self.assertTrue(_contains_product_code("f007783_V넥", "F007783"))
        self.assertFalse(_contains_product_code("G1271540_다른 상품", "G127154"))
        self.assertFalse(_contains_product_code("FG127154_다른 상품", "G127154"))
        self.assertFalse(_contains_product_code("상품 목록", ""))

    async def test_page_search_text_without_product_row_is_not_success(self):
        page = MagicMock()
        rows = MagicMock()
        rows.count = AsyncMock(return_value=0)
        page.locator.return_value.filter.return_value = rows
        self.assertIsNone(await _matching_product_row(page, "G127154"))
        page.locator.assert_called_once_with("table tbody tr")

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
        self.assertEqual(source_button.click.await_count, 2)
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
