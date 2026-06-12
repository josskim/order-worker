from __future__ import annotations

import unittest

from order_worker.sites.specialoffer_invoice import parse_result


class SpecialOfferInvoiceResultTests(unittest.TestCase):
    def test_parses_specialoffer_result_counts(self) -> None:
        result = parse_result(
            "총건수\n총배송건수\t2건\n완료건수\t2건\n실패건수\t0건"
        )

        self.assertTrue(result["success"])
        self.assertEqual(2, result["totalCount"])
        self.assertEqual(2, result["uploadedCount"])
        self.assertEqual(0, result["failedCount"])

    def test_partial_processing_is_failure(self) -> None:
        result = parse_result(
            "총배송건수 2건\n완료건수 1건\n실패건수 0건"
        )

        self.assertFalse(result["success"])
        self.assertEqual(2, result["totalCount"])
        self.assertEqual(1, result["uploadedCount"])

    def test_parses_failed_serial_numbers(self) -> None:
        result = parse_result(
            "총배송건수 2건\n완료건수 1건\n실패건수 1건\n일련번호: 1234567890"
        )

        self.assertFalse(result["success"])
        self.assertEqual(["1234567890"], result["failedSerials"])

    def test_missing_result_counts_is_failure(self) -> None:
        result = parse_result("엑셀일괄배송처리")

        self.assertFalse(result["success"])
        self.assertEqual(0, result["uploadedCount"])


if __name__ == "__main__":
    unittest.main()
