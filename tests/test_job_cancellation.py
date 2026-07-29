from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from order_worker import main
from order_worker.run_history import ClaimResult


class JobCancellationTests(unittest.IsolatedAsyncioTestCase):
    @patch("order_worker.main.complete_job")
    @patch("order_worker.main.run_command", new_callable=AsyncMock)
    @patch("order_worker.main.is_job_cancelled")
    @patch("order_worker.main.claim_job")
    async def test_cancelled_job_does_not_start_work(
        self,
        claim_job: Mock,
        is_cancelled: Mock,
        run_command: AsyncMock,
        complete_job: Mock,
    ) -> None:
        claim_job.return_value = ClaimResult(acquired=True)
        is_cancelled.return_value = True

        with patch("order_worker.main.config.ORDER_WORKER_JOB_ID", "job-1"):
            exit_code = await main.run_job_command("collect")

        self.assertEqual(exit_code, 0)
        run_command.assert_not_awaited()
        complete_job.assert_not_called()

    async def test_order_collection_stops_between_suppliers(self) -> None:
        first_runner = AsyncMock(return_value=[{"site": "first", "success": True}])
        second_runner = AsyncMock(return_value=[{"site": "second", "success": True}])
        cancellation_checks = iter([False, True])

        with (
            patch.dict(main.SITE_RUNNERS, {"first": first_runner, "second": second_runner}, clear=True),
            patch("order_worker.main.cleanup_downloads"),
        ):
            with self.assertRaises(main.JobCancelled):
                await main.run_sites(
                    ["first", "second"],
                    should_cancel=lambda: next(cancellation_checks),
                )

        first_runner.assert_awaited_once()
        second_runner.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
