from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import xlrd
import xlwt

from order_worker.sites.invoice_utils import (
    download_invoice_export_with_count,
    parse_success_fail_counts,
    resave_xls_with_excel,
)


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


class ResaveSpecialOfferXlsTests(unittest.TestCase):
    def test_resaves_biff8_without_windows_excel(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "special.xls"
            source = xlwt.Workbook(encoding="utf-8")
            sheet = source.add_sheet("엑셀일괄배송처리")
            sheet.write(0, 0, "일련번호")
            sheet.write(0, 1, "송장번호")
            sheet.write(1, 0, "26072912172635")
            sheet.write(1, 1, "1234567890")
            source.save(str(path))

            resave_xls_with_excel(path)

            result = xlrd.open_workbook(str(path), on_demand=True)
            result_sheet = result.sheet_by_name("엑셀일괄배송처리")
            self.assertEqual(result_sheet.cell_value(0, 0), "일련번호")
            self.assertEqual(result_sheet.cell_value(1, 0), "26072912172635")
            self.assertEqual(result_sheet.cell_value(1, 1), "1234567890")
            result.release_resources()


if __name__ == "__main__":
    unittest.main()
