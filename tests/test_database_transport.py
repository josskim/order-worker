from order_worker.database_transport import _registration_sites


def test_registration_sites_collects_successful_non_preview_sites() -> None:
    product_id, sites = _registration_sites(
        {
            "request": {"productId": 127151},
            "summary": [
                {"siteCode": "ownerclan", "success": True},
                {"site": "onchannel", "success": True},
                {"site": "namdo", "success": True, "preview": True},
                {"site": "domesin", "success": False},
            ],
        }
    )

    assert product_id == 127151
    assert sites == ["ownerclan", "onch3"]


def test_registration_sites_ignores_invalid_product() -> None:
    assert _registration_sites({"request": {}, "summary": []}) == (0, [])
