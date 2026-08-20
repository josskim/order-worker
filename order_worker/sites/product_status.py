from __future__ import annotations

from functools import partial
from typing import Any

from order_worker.sites import domeggook_status, domesin_status, ownerclan_status, onchannel_status, specialoffer_status
from order_worker.sites.status_utils import failed

RUNNERS = {
    "ownerclan": ownerclan_status.run,
    "Fownerclan": partial(ownerclan_status.run, account_code="Fownerclan"),
    "onchannel": onchannel_status.run,
    "Fonch3": partial(onchannel_status.run, account_code="Fonch3"),
    "domesin": domesin_status.run,
    "specialoffer": specialoffer_status.run,
    "domeggook": domeggook_status.run,
    "Fdomeggook": partial(domeggook_status.run, account_code="Fdomeggook"),
}

LABELS = {
    "ownerclan": "오너클랜",
    "Fownerclan": "F오너클랜",
    "onchannel": "온채널",
    "Fonch3": "F온채널",
    "domeggook": "도매꾹",
    "Fdomeggook": "F도매꾹",
    "specialoffer": "스페셜오퍼",
    "domesin": "도매의신",
}


async def run_sites(action: str, product_code: str, option_name: str | None, sites: list[str], preview: bool = False) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for site_code in sites:
        runner = RUNNERS.get(site_code)
        if runner is None:
            results.append(failed(LABELS.get(site_code, site_code), site_code, action, product_code, "아직 자동 품절 로직이 배포되지 않아 처리하지 않았습니다."))
            continue
        try:
            results.append(await runner(action=action, product_code=product_code, option_name=option_name, preview=preview))
        except Exception as exc:
            results.append(failed(LABELS.get(site_code, site_code), site_code, action, product_code, exc))
    return results
