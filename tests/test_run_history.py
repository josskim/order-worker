from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from order_worker.run_history import claim_run, complete_run


class RunHistoryTests(unittest.TestCase):
    @patch("order_worker.run_history.requests.post")
    def test_claim_run_returns_acquired_status(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "success": True,
            "acquired": False,
            "run": {"status": "succeeded"},
        }
        post.return_value = response

        result = claim_run(
            run_id="invoice-all-1234",
            task_key="invoice-upload-real-fake",
            run_date="2026-07-16",
        )

        self.assertFalse(result.acquired)
        self.assertEqual(result.existing_status, "succeeded")
        response.raise_for_status.assert_called_once()

    @patch("order_worker.run_history.requests.post")
    def test_complete_run_posts_completion(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {"success": True}
        post.return_value = response

        complete_run(
            run_id="invoice-all-1234",
            status="partial",
            details={"failed_types": ["real"]},
        )

        response.raise_for_status.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["action"], "complete")
        self.assertEqual(payload["status"], "partial")


if __name__ == "__main__":
    unittest.main()
