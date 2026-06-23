from __future__ import annotations

import requests

from order_worker import config
from order_worker.sites.invoice_utils import download_invoice_export


SITE_CODE = "sister"
LABEL = "시스터"


def upload_invoice_file(file_path) -> dict:
    if not config.SISTER_INVOICE_UPLOAD_TOKEN and not config.SISTER_ORDER_EXPORT_TOKEN:
        raise RuntimeError("Sister API token is required for invoice upload")

    print(f"PROGRESS: [{LABEL}] 송장 엑셀 API 업로드: {file_path.name}")
    with file_path.open("rb") as file_obj:
        response = requests.post(
            config.SISTER_INVOICE_UPLOAD_API_URL,
            headers={
                "x-sister-upload-token": config.SISTER_INVOICE_UPLOAD_TOKEN,
                "x-sister-order-export-token": config.SISTER_ORDER_EXPORT_TOKEN,
            },
            files={
                "file": (
                    file_path.name,
                    file_obj,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            timeout=120,
        )

    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok:
        message = payload.get("error") or response.text[:500] or f"HTTP {response.status_code}"
        raise RuntimeError(f"시스터 송장 업로드 실패 ({response.status_code}): {message}")
    return {
        "success": bool(payload.get("success")),
        "uploadedCount": int(payload.get("successCount") or 0),
        "failedCount": int(payload.get("failedCount") or 0),
        "message": "시스터 송장 업로드 결과를 확인했습니다.",
        "failedOrders": payload.get("failures") or [],
        "resultText": str(payload)[:1000],
    }


async def run_one(export_type: str, start_date: str, end_date: str, preview: bool = False) -> dict:
    file_path = download_invoice_export(SITE_CODE, export_type, start_date, end_date)
    print(f"PROGRESS: [{LABEL}] 인트라넷 업로드용 송장 엑셀 다운로드 완료: {file_path}")

    if preview:
        return {
            "site": LABEL,
            "siteCode": SITE_CODE,
            "type": export_type,
            "success": True,
            "uploadedCount": 0,
            "failedCount": 0,
            "message": "송장 엑셀 다운로드까지 완료했습니다.",
            "preview": True,
        }

    result = upload_invoice_file(file_path)
    return {"site": LABEL, "siteCode": SITE_CODE, "type": export_type, **result}


async def run(site_names: list[str], export_type: str, start_date: str, end_date: str, preview: bool = False) -> list[dict]:
    results: list[dict] = []
    for _site in site_names:
        try:
            results.append(await run_one(export_type, start_date, end_date, preview=preview))
        except Exception as exc:
            results.append({"site": LABEL, "siteCode": SITE_CODE, "type": export_type, "success": False, "error": str(exc)})
    return results
