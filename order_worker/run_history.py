from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from order_worker import config


@dataclass(frozen=True)
class ClaimResult:
    acquired: bool
    existing_status: str | None = None


def _headers() -> dict[str, str]:
    if not config.ORDER_WORKER_RUN_HISTORY_TOKEN:
        return {}
    return {"x-order-worker-token": config.ORDER_WORKER_RUN_HISTORY_TOKEN}


def claim_run(
    *,
    run_id: str,
    task_key: str,
    run_date: str,
    details: dict[str, Any] | None = None,
) -> ClaimResult:
    response = requests.post(
        config.INTRANET_RUN_HISTORY_API_URL,
        headers=_headers(),
        json={
            "action": "claim",
            "run_id": run_id,
            "task_key": task_key,
            "run_date": run_date,
            "details": details or {},
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("error") or "Run history claim failed")
    existing = payload.get("run") or {}
    return ClaimResult(
        acquired=bool(payload.get("acquired")),
        existing_status=existing.get("status"),
    )


def complete_run(
    *,
    run_id: str,
    status: str,
    details: dict[str, Any] | None = None,
) -> None:
    response = requests.post(
        config.INTRANET_RUN_HISTORY_API_URL,
        headers=_headers(),
        json={
            "action": "complete",
            "run_id": run_id,
            "status": status,
            "details": details or {},
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("error") or "Run history completion failed")
