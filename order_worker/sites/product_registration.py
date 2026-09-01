from __future__ import annotations

from typing import Any

from order_worker.sites import domeggook_registration, onchannel_registration, ownerclan_registration


RUNNERS = {
    "ownerclan": ownerclan_registration.run_account,
    "Fownerclan": ownerclan_registration.run_account,
    "onch3": onchannel_registration.run_account,
    "Fonch3": onchannel_registration.run_account,
    "domeggook": domeggook_registration.run_account,
    "Fdomeggook": domeggook_registration.run_account,
}


async def run_sites(
    request: dict[str, Any],
    preview: bool = False,
    on_progress=None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for account in request.get("accounts", []):
        site_code = str(account.get("siteCode") or "")
        if on_progress:
            on_progress(site_code, results.copy())
        runner = RUNNERS.get(site_code)
        if runner is None:
            result = {
                "site": str(account.get("siteLabel") or site_code),
                "siteCode": site_code,
                "success": False,
                "productCode": str(account.get("code") or ""),
                "error": f"지원하지 않는 상품등록 사이트입니다: {site_code}",
            }
        else:
            result = await runner(request, account, preview=preview)
        results.append(result)
        if on_progress:
            on_progress(None, results.copy())
    return results
