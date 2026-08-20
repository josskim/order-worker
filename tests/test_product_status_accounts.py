from order_worker.sites.product_status import LABELS, RUNNERS


def test_status_runners_include_secondary_vendor_accounts():
    expected = {
        "ownerclan": "오너클랜",
        "Fownerclan": "F오너클랜",
        "onchannel": "온채널",
        "Fonch3": "F온채널",
        "domeggook": "도매꾹",
        "Fdomeggook": "F도매꾹",
    }

    for code, label in expected.items():
        assert code in RUNNERS
        assert LABELS[code] == label
