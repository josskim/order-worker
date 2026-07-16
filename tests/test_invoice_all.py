from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from order_worker import main
from order_worker.run_history import ClaimResult


class UploadAllInvoiceTypesTests(unittest.IsolatedAsyncioTestCase):
    @patch("order_worker.main.complete_run")
    @patch("order_worker.main.upload_invoices_command", new_callable=AsyncMock)
    @patch("order_worker.main.claim_run")
    async def test_runs_real_then_fake_and_completes(
        self,
        claim: Mock,
        upload: AsyncMock,
        complete: Mock,
    ) -> None:
        claim.return_value = ClaimResult(acquired=True)
        upload.side_effect = [0, 1]

        exit_code = await main.upload_all_invoice_types_command()

        self.assertEqual(exit_code, 0)
        self.assertEqual([call.args[0].type for call in upload.call_args_list], ["real", "fake"])
        self.assertEqual(complete.call_args.kwargs["status"], "partial")
        self.assertEqual(complete.call_args.kwargs["details"]["failed_types"], ["fake"])

    @patch("order_worker.main.complete_run")
    @patch("order_worker.main.upload_invoices_command", new_callable=AsyncMock)
    @patch("order_worker.main.claim_run")
    async def test_duplicate_claim_does_not_upload(
        self,
        claim: Mock,
        upload: AsyncMock,
        complete: Mock,
    ) -> None:
        claim.return_value = ClaimResult(acquired=False, existing_status="succeeded")

        exit_code = await main.upload_all_invoice_types_command()

        self.assertEqual(exit_code, 0)
        upload.assert_not_awaited()
        complete.assert_not_called()


if __name__ == "__main__":
    unittest.main()
