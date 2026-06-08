from __future__ import annotations

import unittest

from order_worker.sites.invoice_utils import parse_success_fail_counts


class ParseSuccessFailCountsTests(unittest.TestCase):
    def test_parses_domeggook_line_break_format(self) -> None:
        text = "업로드 결과\n총 건수\n8\n성공\n5\n실패\n3\n확인"

        self.assertEqual(parse_success_fail_counts(text), (5, 3))

    def test_parses_counts_with_units_and_commas(self) -> None:
        text = "성공: 1,234건 실패： 56 건"

        self.assertEqual(parse_success_fail_counts(text), (1234, 56))

    def test_returns_none_when_counts_are_absent(self) -> None:
        self.assertEqual(parse_success_fail_counts("업로드 처리중입니다."), (None, None))


if __name__ == "__main__":
    unittest.main()
