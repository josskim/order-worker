from __future__ import annotations

from typing import Any

from order_worker.sites import domeggook_registration, domesin_registration, laf, namdo_registration, onchannel_registration, ownerclan_registration, specialoffer_registration, sinsang_registration


RUNNERS = {
    "account1": sinsang_registration.run_account,
    "account2": sinsang_registration.run_account,
    "ownerclan": ownerclan_registration.run_account,
    "Fownerclan": ownerclan_registration.run_account,
    "onch3": onchannel_registration.run_account,
    "Fonch3": onchannel_registration.run_account,
    "domeggook": domeggook_registration.run_account,
    "Fdomeggook": domeggook_registration.run_account,
    "specialoffer": specialoffer_registration.run_account,
    "domesin": domesin_registration.run_account,
    "namdo": namdo_registration.run_account,
    "cafe_laf": laf.run_registration,
}


async def run_sites(
    request: dict[str, Any],
    preview: bool = False,
    on_progress=None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = list(request.get("preResults") or [])
    for account in request.get("accounts", []):
        site_code = str(account.get("siteCode") or "")
        if any(result.get("siteCode") == site_code for result in results):
            continue
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
            try:
                site_request = request
                confirmed_paths = request.get("siteCategoryPaths")
                if confirmed_paths is not None:
                    path = confirmed_paths.get(site_code)
                    if site_code not in {"sister", "cafe_laf"} and not path:
                        raise RuntimeError("사이트별 카테고리 설정을 완료해 주세요.")
                    if path:
                        site_request = {**request, "categoryPath": list(path)}
                        section = {"domeggook": "domeggook", "Fdomeggook": "domeggook", "domesin": "domesin", "specialoffer": "specialoffer", "namdo": "namdo"}.get(site_code)
                        if section:
                            site_request[section] = {**(request.get(section) or {}), "categoryPath": list(path)}
                result = await runner(site_request, account, preview=preview)
            except Exception as exc:
                result = {
                    "site": str(account.get("siteLabel") or site_code),
                    "siteCode": site_code,
                    "success": False,
                    "productCode": str(account.get("code") or ""),
                    "error": str(exc) or type(exc).__name__,
                }
        results.append(result)
        if on_progress:
            on_progress(None, results.copy())
    return results
