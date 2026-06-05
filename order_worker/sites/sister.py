from __future__ import annotations

from datetime import datetime
from pathlib import Path

import requests

from order_worker import config
from order_worker.sites.utils import DOWNLOAD_DIR, upload_to_intranet


SITE_CODE = "sister"
LABEL = "시스터"


async def run() -> list[dict]:
    if not config.SISTER_ORDER_EXPORT_TOKEN:
        return [{
            "site": LABEL,
            "success": False,
            "error": "SISTER_ORDER_EXPORT_TOKEN is required for Sister order export",
        }]

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    file_path = Path(DOWNLOAD_DIR) / f"sister_orders_{timestamp}.xlsx"

    try:
        response = requests.get(
            config.SISTER_ORDER_EXPORT_API_URL,
            headers={"x-sister-order-export-token": config.SISTER_ORDER_EXPORT_TOKEN},
            timeout=90,
        )
        response.raise_for_status()
        file_path.write_bytes(response.content)
        print(f"PROGRESS: [{LABEL}] 주문서 엑셀 다운로드 완료: {file_path}")
        result = upload_to_intranet(str(file_path), SITE_CODE)
        result.setdefault("site", LABEL)
        return [result]
    except Exception as exc:
        return [{"site": LABEL, "success": False, "error": str(exc)}]
