import unittest
from unittest.mock import AsyncMock, patch

from order_worker.sites import product_status


class ProductStatusProductCodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_f_accounts_use_f_code_while_regular_accounts_keep_g_code(self):
        ownerclan = AsyncMock(
            side_effect=lambda **kwargs: {
                "siteCode": "ownerclan",
                "productCode": kwargs["product_code"],
                "success": True,
            }
        )
        fownerclan = AsyncMock(
            side_effect=lambda **kwargs: {
                "siteCode": "Fownerclan",
                "productCode": kwargs["product_code"],
                "success": True,
            }
        )

        with patch.dict(
            product_status.RUNNERS,
            {"ownerclan": ownerclan, "Fownerclan": fownerclan},
            clear=True,
        ):
            results = await product_status.run_sites(
                action="product-soldout",
                product_code="G126655",
                option_name=None,
                sites=["ownerclan", "Fownerclan"],
                site_product_codes={"Fownerclan": "F007275"},
            )

        self.assertEqual(ownerclan.call_args.kwargs["product_code"], "G126655")
        self.assertEqual(fownerclan.call_args.kwargs["product_code"], "F007275")
        self.assertEqual([result["productCode"] for result in results], ["G126655", "F007275"])

    async def test_missing_f_code_is_reported_without_running_site(self):
        runner = AsyncMock()

        with patch.dict(product_status.RUNNERS, {"Fonch3": runner}, clear=True):
            results = await product_status.run_sites(
                action="option-soldout",
                product_code="G126655",
                option_name="민트/FREE",
                sites=["Fonch3"],
                site_product_codes={"Fonch3": None},
            )

        runner.assert_not_awaited()
        self.assertFalse(results[0]["success"])
        self.assertEqual(results[0]["productCode"], "G126655")
        self.assertIn("F 품절코드", results[0]["error"])


if __name__ == "__main__":
    unittest.main()
