from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file(ENV_PATH)


def _default_runtime_dir() -> Path:
    if os.getenv("ORDER_WORKER_RUNTIME_DIR"):
        return Path(os.environ["ORDER_WORKER_RUNTIME_DIR"])
    if os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PROJECT_ID"):
        return Path("/tmp/order-worker")
    return PROJECT_ROOT


RUNTIME_DIR = _default_runtime_dir()
ORDER_TELEGRAM_ENV_PATH = Path(
    os.getenv("ORDER_TELEGRAM_ENV", PROJECT_ROOT / "runtime" / "secrets" / "order-telegram.env")
)
_load_env_file(ORDER_TELEGRAM_ENV_PATH)
DOWNLOAD_DIR = Path(os.getenv("ORDER_WORKER_DOWNLOAD_DIR", RUNTIME_DIR / "downloads"))
ARCHIVE_DIR = Path(os.getenv("ORDER_WORKER_ARCHIVE_DIR", RUNTIME_DIR / "archive"))
LOG_DIR = Path(os.getenv("ORDER_WORKER_LOG_DIR", RUNTIME_DIR / "logs"))
LOCK_FILE = Path(os.getenv("ORDER_WORKER_LOCK_FILE", RUNTIME_DIR / "order-worker.lock"))

INTRANET_API_URL = os.getenv("INTRANET_API_URL", "http://localhost:3001/api/order-import")
INTRANET_LOG_API_URL = os.getenv("INTRANET_LOG_API_URL", "http://localhost:3001/api/order-import/log")
INTRANET_RUN_HISTORY_API_URL = os.getenv(
    "INTRANET_RUN_HISTORY_API_URL",
    "http://localhost:3001/api/order-worker/run-history",
)
INTRANET_JOB_API_URL = os.getenv(
    "INTRANET_JOB_API_URL",
    "http://localhost:3001/api/order-worker/jobs/worker",
)
ORDER_WORKER_RUN_HISTORY_TOKEN = os.getenv("ORDER_WORKER_RUN_HISTORY_TOKEN", "")
ORDER_WORKER_JOB_ID = os.getenv("ORDER_WORKER_JOB_ID", "")
ORDER_WORKER_TRANSPORT = os.getenv("ORDER_WORKER_TRANSPORT", "http").strip().lower()
DIRECT_URL = os.getenv("DIRECT_URL", "").strip()
ORDER_WORKER_LOCAL_POLL_SECONDS = max(15, int(os.getenv("ORDER_WORKER_LOCAL_POLL_SECONDS", "60")))
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
    "https://www.prahashop.co.kr/api/seller/invoice-upload",
)
SISTER_INVOICE_UPLOAD_TOKEN = os.getenv("SISTER_INVOICE_UPLOAD_TOKEN", "")
SISTER_ORDER_EXPORT_API_URL = os.getenv(
    "SISTER_ORDER_EXPORT_API_URL",
    "https://prahashop.co.kr/api/seller/orders/export",
)
SISTER_ORDER_EXPORT_TOKEN = os.getenv("SISTER_ORDER_EXPORT_TOKEN", "")
SISTER_PRODUCT_STATUS_API_URL = os.getenv(
    "SISTER_PRODUCT_STATUS_API_URL",
    "https://www.prahashop.co.kr/api/internal/product-status",
)
SISTER_PRODUCT_STATUS_TOKEN = os.getenv(
    "SISTER_PRODUCT_STATUS_TOKEN",
    SISTER_ORDER_EXPORT_TOKEN,
)

# Order collection/invoice notifications can use a dedicated bot while the
# inventory worker keeps reading the legacy TELEGRAM_* reservation bot values.
TELEGRAM_BOT_TOKEN = os.getenv("ORDER_TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_CHAT_ID = os.getenv("ORDER_TELEGRAM_CHAT_ID", os.getenv("TELEGRAM_CHAT_ID", ""))

DOMEGGOOK_ACTION_WAIT_SECONDS = int(
    os.getenv("DOMEGGOOK_ACTION_WAIT_SECONDS", "90")
)
DOMEGGOOK_WAIT_SECONDS = int(os.getenv("DOMEGGOOK_WAIT_SECONDS", "600"))
DOMEGGOOK_POLL_SECONDS = int(os.getenv("DOMEGGOOK_POLL_SECONDS", "3"))
DOMEGGOOK_DOWNLOAD_TIMEOUT_SECONDS = int(
    os.getenv("DOMEGGOOK_DOWNLOAD_TIMEOUT_SECONDS", "90")
)
HEADLESS = os.getenv("ORDER_WORKER_HEADLESS", "1").lower() not in {"0", "false", "no"}

LAF_CAFE_ID = os.getenv("LAF_CAFE_ID", "26667015").strip()
LAF_CAFE_SLUG = os.getenv("LAF_CAFE_SLUG", "liveprice").strip()
LAF_CHROME_DEBUG_PORT = int(os.getenv("LAF_CHROME_DEBUG_PORT", "9223"))
LAF_CHROME_PROFILE_DIR = Path(
    os.getenv("LAF_CHROME_PROFILE_DIR", PROJECT_ROOT.parent / "intranet" / "data" / "laf-chrome-profile")
)


def ensure_directories() -> None:
    for path in (DOWNLOAD_DIR, ARCHIVE_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
