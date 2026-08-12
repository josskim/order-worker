from __future__ import annotations

import unittest

from order_worker.sites.domesin_invoice import calculate_retry_start_date, parse_result


class DomesinInvoiceResultTests(unittest.TestCase):
    def test_requires_positive_confirmed_count(self) -> None:
        result = parse_result("송장엑셀등록", expected_count=1)

        self.assertFalse(result["success"])
        self.assertEqual(result["confirmedCount"], 0)

    def test_accepts_explicit_matching_success_count(self) -> None:
        result = parse_result("성공: 2건 실패: 0건", expected_count=2)

        self.assertTrue(result["success"])
        self.assertEqual(result["confirmedCount"], 2)

    def test_rejects_mismatched_success_count(self) -> None:
        result = parse_result("1건 정상 처리되었습니다.", expected_count=2)

        self.assertFalse(result["success"])
        self.assertEqual(result["confirmedCount"], 1)

    def test_uses_success_dialog_when_count_is_not_in_body(self) -> None:
        result = parse_result(
            "송장엑셀등록",
            expected_count=3,
            dialog_messages=["송장번호 등록이 완료되었습니다."],
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["uploadedCount"], 3)

    def test_uses_submit_response_when_page_returns_to_empty_upload_form(self) -> None:
        result = parse_result(
            "송장엑셀등록",
            expected_count=1,
            response_texts=[
                '<script>alert("송장번호가 등록되었습니다."); history.back();</script>'
            ],
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["confirmedCount"], 1)

    def test_single_already_processed_order_is_confirmed(self) -> None:
        result = parse_result("이미 배송처리된 주문입니다.", expected_count=1)

        self.assertTrue(result["success"])
        self.assertEqual(result["alreadyProcessedCount"], 1)

    def test_real_invoice_uses_three_day_lookback(self) -> None:
        self.assertEqual(calculate_retry_start_date("real", "2026-07-22"), "2026-07-20")
        self.assertEqual(calculate_retry_start_date("fake", "2026-07-22"), "2026-07-22")


if __name__ == "__main__":
    unittest.main()
