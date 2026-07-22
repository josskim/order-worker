from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from order_worker.sites.invoice_utils import download_invoice_export_with_count, parse_success_fail_counts


class ParseSuccessFailCountsTests(unittest.TestCase):
    def test_parses_domeggook_line_break_format(self) -> None:
        text = "업로드 결과\n총 건수\n8\n성공\n5\n실패\n3\n확인"

        self.assertEqual(parse_success_fail_counts(text), (5, 3))

    def test_parses_counts_with_units_and_commas(self) -> None:
        text = "성공: 1,234건 실패： 56 건"

        self.assertEqual(parse_success_fail_counts(text), (1234, 56))

    def test_returns_none_when_counts_are_absent(self) -> None:
        self.assertEqual(parse_success_fail_counts("업로드 처리중입니다."), (None, None))


class DownloadInvoiceExportTests(unittest.TestCase):
    @patch("order_worker.sites.invoice_utils.requests.get")
    def test_returns_exported_row_count_header(self, get: Mock) -> None:
        response = Mock()
        response.status_code = 200
        response.content = b"xls"
        response.headers = {
            "content-disposition": 'attachment; filename="domegod.xls"',
            "x-invoice-row-count": "3",
        }
        get.return_value = response

        with TemporaryDirectory() as temp_dir, patch(
            "order_worker.sites.invoice_utils.config.DOWNLOAD_DIR",
            Path(temp_dir),
        ):
            path, row_count = download_invoice_export_with_count(
                "domegod",
                "real",
                "2026-07-20",
                "2026-07-22",
            )

        self.assertEqual(path.name, "domegod.xls")
        self.assertEqual(row_count, 3)


if __name__ == "__main__":
    unittest.main()
