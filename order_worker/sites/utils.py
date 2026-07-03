from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path

import requests

from order_worker import config
from order_worker.notifier import send_telegram_message


DOWNLOAD_DIR = str(config.DOWNLOAD_DIR)
INTRANET_API = config.INTRANET_API_URL


def archive_file(file_path: str, site: str) -> None:
    source = Path(file_path)
    if not source.exists():
        return

    config.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = config.ARCHIVE_DIR / f"{timestamp}-{site}-{source.name}"
    shutil.copy2(source, target)


def upload_to_intranet(file_path: str, site: str) -> dict:
    try:
        archive_file(file_path, site)

        with open(file_path, "rb") as file:
            filename = os.path.basename(file_path)
            response = requests.post(
                INTRANET_API,
                files={"file": (filename, file, "application/octet-stream")},
                data={"site": site},
                timeout=90,
            )
        response.raise_for_status()
        result = response.json()
        if not result.get("success") and not result.get("error"):
            errors = result.get("errors")
            if isinstance(errors, list) and errors:
                result["error"] = "; ".join(str(item) for item in errors if item)

        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass

        return result
    except Exception as exc:
        return {"success": False, "error": str(exc)}
