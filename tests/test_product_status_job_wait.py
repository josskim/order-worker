import unittest
from unittest.mock import AsyncMock, Mock, patch

from order_worker import main
from order_worker.run_history import ClaimResult


class ProductStatusJobWaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_waits_until_held_job_is_released(self):
        request = {
            "action": "product-restock",
            "productCode": "G126121",
            "optionName": None,
            "siteProductCodes": {"Fownerclan": "F007275"},
            "sites": ["sister"],
        }
        claims = [
            ClaimResult(acquired=False, existing_status="held", job={}),
            ClaimResult(
                acquired=True,
                existing_status="running",
                job={"result": {"request": request}},
            ),
        ]
        claim_job = Mock(side_effect=claims)
        run_sites = AsyncMock(
            return_value=[{"siteCode": "sister", "success": True}]
        )
        complete_job = Mock()

        with (
            patch("order_worker.main.claim_job", claim_job),
            patch("order_worker.main.asyncio.sleep", new=AsyncMock()),
            patch("order_worker.main.is_job_cancelled", return_value=False),
            patch("order_worker.main.product_status.run_sites", run_sites),
            patch("order_worker.main.complete_job", complete_job),
            patch("order_worker.main.config.ORDER_WORKER_JOB_ID", "job-1"),
        ):
            exit_code = await main.run_job_command("product-status")

        self.assertEqual(exit_code, 0)
        self.assertEqual(claim_job.call_count, 2)
        run_sites.assert_awaited_once()
        self.assertEqual(
            run_sites.call_args.kwargs["site_product_codes"],
            {"Fownerclan": "F007275"},
        )
        self.assertEqual(complete_job.call_args.kwargs["status"], "succeeded")
