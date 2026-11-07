import unittest
from unittest.mock import AsyncMock, patch

from order_worker.sites import product_registration


class CategorySelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_site_paths_are_isolated_and_override_legacy_sections(self):
        runners = {key: AsyncMock(return_value={"success": True, "siteCode": key}) for key in ["ownerclan", "Fownerclan", "domesin", "Fdomeggook"]}
        paths = {key: [key, "actual leaf"] for key in runners}
        request = {"accounts": [{"siteCode": key} for key in runners], "categoryPath": ["wrong"], "domesin": {"categoryPath": ["wrong"], "shippingFee": 3000}, "siteCategoryPaths": paths}
        with patch.dict(product_registration.RUNNERS, runners, clear=True):
            results = await product_registration.run_sites(request, preview=True)
        self.assertTrue(all(item["success"] for item in results))
        for key, runner in runners.items():
            actual = runner.await_args.args[0]
            self.assertEqual(actual["categoryPath"], paths[key])
            if key == "domesin":
                self.assertEqual(actual["domesin"]["categoryPath"], paths[key])
                self.assertEqual(actual["domesin"]["shippingFee"], 3000)
            if key == "Fdomeggook":
                self.assertEqual(actual["domeggook"]["categoryPath"], paths[key])
        self.assertEqual(request["categoryPath"], ["wrong"])
        self.assertEqual(request["domesin"]["categoryPath"], ["wrong"])

    async def test_missing_confirmed_site_does_not_invoke_registration(self):
        runner = AsyncMock()
        with patch.dict(product_registration.RUNNERS, {"domesin": runner}, clear=True):
            results = await product_registration.run_sites({"accounts": [{"siteCode": "domesin"}], "siteCategoryPaths": {}})
        runner.assert_not_awaited()
        self.assertFalse(results[0]["success"])
        self.assertIn("카테고리 설정", results[0]["error"])
