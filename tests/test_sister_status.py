import asyncio

from order_worker.sites import sister_status


class FakeResponse:
    ok = True
    status_code = 200
    text = ""

    def json(self):
        return {
            "success": True,
            "site": "시스터",
            "siteCode": "sister",
            "message": "옵션 품절 처리 완료",
            "matchedProducts": 2,
            "matchedOptions": 2,
        }


def test_sister_status_calls_internal_api(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(sister_status.config, "SISTER_PRODUCT_STATUS_API_URL", "https://example.test/api/internal/product-status")
    monkeypatch.setattr(sister_status.config, "SISTER_PRODUCT_STATUS_TOKEN", "secret")
    monkeypatch.setattr(sister_status.requests, "post", fake_post)

    result = asyncio.run(sister_status.run("option-soldout", "G123456", "핑크/FREE"))

    assert result["success"] is True
    assert result["siteCode"] == "sister"
    assert captured["json"] == {
        "action": "option-soldout",
        "productCode": "G123456",
        "optionName": "핑크/FREE",
        "preview": False,
    }
    assert captured["headers"]["x-sister-product-status-token"] == "secret"
