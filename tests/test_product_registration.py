from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from order_worker.sites import product_registration


class ProductRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_dispatches_mixed_accounts_in_requested_order(self):
        owner_runner = AsyncMock(return_value={"siteCode": "ownerclan", "success": True})
        onchannel_runner = AsyncMock(return_value={"siteCode": "onch3", "success": True, "draftSaved": True})
        domeggook_runner = AsyncMock(return_value={"siteCode": "domeggook", "success": True})
        specialoffer_runner = AsyncMock(return_value={"siteCode": "specialoffer", "success": True})
        request = {
            "accounts": [
                {"siteCode": "ownerclan", "code": "G1"},
                {"siteCode": "onch3", "code": "G1"},
                {"siteCode": "domeggook", "code": "G1"},
                {"siteCode": "specialoffer", "code": "G1"},
            ]
        }
        progress = []

        with patch.dict(
            product_registration.RUNNERS,
            {"ownerclan": owner_runner, "onch3": onchannel_runner, "domeggook": domeggook_runner, "specialoffer": specialoffer_runner},
            clear=True,
        ):
            results = await product_registration.run_sites(
                request,
                preview=True,
                on_progress=lambda site, summary: progress.append((site, len(summary))),
            )

        self.assertEqual([result["siteCode"] for result in results], ["ownerclan", "onch3", "domeggook", "specialoffer"])
        self.assertTrue(results[1]["draftSaved"])
        owner_runner.assert_awaited_once_with(request, request["accounts"][0], preview=True)
        onchannel_runner.assert_awaited_once_with(request, request["accounts"][1], preview=True)
        specialoffer_runner.assert_awaited_once_with(request, request["accounts"][3], preview=True)
        self.assertEqual(progress, [("ownerclan", 0), (None, 1), ("onch3", 1), (None, 2), ("domeggook", 2), (None, 3), ("specialoffer", 3), (None, 4)])

    async def test_unsupported_account_is_a_site_failure(self):
        results = await product_registration.run_sites(
            {"accounts": [{"siteCode": "unknown", "siteLabel": "미지원", "code": "G1"}]}
        )

        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["success"])
        self.assertIn("지원하지 않는", results[0]["error"])


if __name__ == "__main__":
    unittest.main()
