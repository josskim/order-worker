from __future__ import annotations

import unittest

from order_worker.main import result_status, summarize_result


class ResultSummaryTests(unittest.TestCase):
    def test_removes_buyer_personal_information(self) -> None:
        result = summarize_result(
            {
                "site": "온채널",
                "success": True,
                "insertedCount": 1,
                "items": [
                    {
                        "buyer": "구매자",
                        "phone": "010-0000-0000",
                        "productName": "상품",
                    }
                ],
            }
        )

        self.assertEqual(result["insertedCount"], 1)
        self.assertNotIn("items", result)
        self.assertNotIn("buyer", str(result))
        self.assertNotIn("phone", str(result))

    def test_partial_result_is_not_total_failure(self) -> None:
        status = result_status(
            [
                {"site": "성공", "success": True},
                {"site": "실패", "success": False},
            ]
        )

        self.assertEqual(status, "partial")


if __name__ == "__main__":
    unittest.main()
