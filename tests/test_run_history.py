from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from order_worker.run_history import claim_job, claim_run, complete_job, complete_run


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

    @patch("order_worker.run_history.requests.post")
    def test_claim_job_uses_worker_job_action(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {
            "success": True,
            "acquired": True,
            "job": {"status": "running"},
        }
        post.return_value = response

        result = claim_job(job_id="job-1", task="collect")

        self.assertTrue(result.acquired)
        self.assertEqual(post.call_args.kwargs["json"]["action"], "claim")

    @patch("order_worker.run_history.requests.post")
    def test_complete_job_posts_sanitized_result(self, post: Mock) -> None:
        response = Mock()
        response.json.return_value = {"success": True}
        post.return_value = response

        complete_job(
            job_id="job-1",
            task="collect",
            status="partial",
            result={"failed_sites": ["specialoffer"]},
        )

        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["action"], "complete")
        self.assertEqual(payload["status"], "partial")


if __name__ == "__main__":
    unittest.main()
