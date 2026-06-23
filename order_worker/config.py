from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


def _load_env_file() -> None:
    if not ENV_PATH.exists():
        return

    for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file()


DOWNLOAD_DIR = Path(os.getenv("ORDER_WORKER_DOWNLOAD_DIR", PROJECT_ROOT / "downloads"))
ARCHIVE_DIR = Path(os.getenv("ORDER_WORKER_ARCHIVE_DIR", PROJECT_ROOT / "archive"))
LOG_DIR = Path(os.getenv("ORDER_WORKER_LOG_DIR", PROJECT_ROOT / "logs"))
LOCK_FILE = Path(os.getenv("ORDER_WORKER_LOCK_FILE", PROJECT_ROOT / "order-worker.lock"))

INTRANET_API_URL = os.getenv("INTRANET_API_URL", "http://localhost:3001/api/order-import")
INTRANET_LOG_API_URL = os.getenv("INTRANET_LOG_API_URL", "http://localhost:3001/api/order-import/log")
INTRANET_INVOICE_EXPORT_API_URL = os.getenv(
    "INTRANET_INVOICE_EXPORT_API_URL",
    "http://localhost:3001/api/invoice-export/file",
)
INTRANET_INVOICE_UPLOAD_MARK_API_URL = os.getenv(
    "INTRANET_INVOICE_UPLOAD_MARK_API_URL",
    "http://localhost:3001/api/invoice-export/mark-uploaded",
)
SISTER_INVOICE_UPLOAD_API_URL = os.getenv(
    "SISTER_INVOICE_UPLOAD_API_URL",
    "https://prahashop.co.kr/api/seller/invoice-upload",
)
SISTER_INVOICE_UPLOAD_TOKEN = os.getenv("SISTER_INVOICE_UPLOAD_TOKEN", "")
SISTER_ORDER_EXPORT_API_URL = os.getenv(
    "SISTER_ORDER_EXPORT_API_URL",
    "http://localhost:3000/api/seller/orders/export",
)
SISTER_ORDER_EXPORT_TOKEN = os.getenv("SISTER_ORDER_EXPORT_TOKEN", "")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

DOMEGGOOK_WAIT_SECONDS = int(os.getenv("DOMEGGOOK_WAIT_SECONDS", "120"))
DOMEGGOOK_POLL_SECONDS = int(os.getenv("DOMEGGOOK_POLL_SECONDS", "5"))
HEADLESS = os.getenv("ORDER_WORKER_HEADLESS", "1").lower() not in {"0", "false", "no"}


def ensure_directories() -> None:
    for path in (DOWNLOAD_DIR, ARCHIVE_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
