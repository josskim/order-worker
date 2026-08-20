from __future__ import annotations

import asyncio

import requests

from order_worker import config


SITE_CODE = "sister"
LABEL = "시스터"


def _request_status(action: str, product_code: str, option_name: str | None, preview: bool) -> dict:
    if not config.SISTER_PRODUCT_STATUS_TOKEN:
        raise RuntimeError("시스터 품절 API 토큰이 설정되지 않았습니다.")

    response = requests.post(
        config.SISTER_PRODUCT_STATUS_API_URL,
        headers={"x-sister-product-status-token": config.SISTER_PRODUCT_STATUS_TOKEN},
        json={
            "action": action,
            "productCode": product_code,
            "optionName": option_name,
            "preview": preview,
        },
        timeout=60,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok or not payload.get("success"):
        message = payload.get("error") or response.text[:500] or f"HTTP {response.status_code}"
        raise RuntimeError(f"시스터 품절 처리 실패 ({response.status_code}): {message}")

    return {
        "site": LABEL,
        "siteCode": SITE_CODE,
        "action": action,
        "productCode": product_code,
        **payload,
    }


async def run(action: str, product_code: str, option_name: str | None = None, preview: bool = False) -> dict:
    print(f"PROGRESS: [{LABEL}] {product_code} {option_name or '상품 전체'} 처리")
    return await asyncio.to_thread(_request_status, action, product_code, option_name, preview)
