import unittest
from unittest.mock import AsyncMock, Mock, patch

from order_worker import main
from order_worker.run_history import ClaimResult


class InvoiceJobTypeTests(unittest.IsolatedAsyncioTestCase):
    async def _run_and_assert(self, task: str, expected_type: str) -> None:
        upload = AsyncMock(return_value=0)
        claim_job = Mock(return_value=ClaimResult(acquired=True))
        complete_job = Mock()

        with (
            patch("order_worker.main.claim_job", claim_job),
            patch("order_worker.main.is_job_cancelled", return_value=False),
            patch("order_worker.main.upload_invoices_command", upload),
            patch("order_worker.main.complete_job", complete_job),
            patch("order_worker.main.config.ORDER_WORKER_JOB_ID", "job-1"),
        ):
            exit_code = await main.run_job_command(task)

        self.assertEqual(exit_code, 0)
        claim_job.assert_called_once_with(job_id="job-1", task=task)
        upload.assert_awaited_once()
        args = upload.await_args.args[0]
        self.assertTrue(args.all)
        self.assertEqual(args.type, expected_type)
        self.assertFalse(args.preview)
        self.assertEqual(complete_job.call_args.kwargs["task"], task)
        self.assertEqual(complete_job.call_args.kwargs["result"]["invoice_type"], expected_type)

    async def test_real_invoice_job_uploads_only_real_invoices(self) -> None:
        await self._run_and_assert("invoices-real", "real")

    async def test_fake_invoice_job_uploads_only_fake_invoices(self) -> None:
        await self._run_and_assert("invoices-fake", "fake")


if __name__ == "__main__":
    unittest.main()
