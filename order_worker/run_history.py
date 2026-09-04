from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests

from order_worker import config


def _uses_database() -> bool:
    return config.ORDER_WORKER_TRANSPORT == "database"


@dataclass(frozen=True)
class ClaimResult:
    acquired: bool
    existing_status: str | None = None
    job: dict[str, Any] | None = None


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
    if _uses_database():
        from order_worker import database_transport

        acquired, run = database_transport.claim_run(run_id, task_key, run_date, details or {})
        return ClaimResult(acquired=acquired, existing_status=(run or {}).get("status"))
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
    if _uses_database():
        from order_worker import database_transport

        database_transport.complete_run(run_id, status, details or {})
        return
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


def claim_job(*, job_id: str, task: str) -> ClaimResult:
    if _uses_database():
        from order_worker import database_transport

        acquired, job = database_transport.claim_job(job_id, task)
        return ClaimResult(
            acquired=acquired,
            existing_status=(job or {}).get("status"),
            job=job,
        )
    response = requests.post(
        config.INTRANET_JOB_API_URL,
        headers=_headers(),
        json={
            "action": "claim",
            "job_id": job_id,
            "task": task,
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("error") or "Job claim failed")
    job = payload.get("job") or {}
    return ClaimResult(
        acquired=bool(payload.get("acquired")),
        existing_status=job.get("status"),
        job=job,
    )


def is_job_cancelled(*, job_id: str, task: str) -> bool:
    if _uses_database():
        from order_worker import database_transport

        return database_transport.is_job_cancelled(job_id, task)
    response = requests.post(
        config.INTRANET_JOB_API_URL,
        headers=_headers(),
        json={
            "action": "status",
            "job_id": job_id,
            "task": task,
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("error") or "Job status check failed")
    return bool(payload.get("cancelled"))


def update_job_progress(
    *,
    job_id: str,
    task: str,
    result: dict[str, Any],
) -> None:
    if _uses_database():
        from order_worker import database_transport

        database_transport.update_job_progress(job_id, task, result)
        return
    response = requests.post(
        config.INTRANET_JOB_API_URL,
        headers=_headers(),
        json={
            "action": "progress",
            "job_id": job_id,
            "task": task,
            "result": result,
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("error") or "Job progress update failed")


def complete_job(
    *,
    job_id: str,
    task: str,
    status: str,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    if _uses_database():
        from order_worker import database_transport

        database_transport.complete_job(job_id, task, status, result or {}, error)
        return
    response = requests.post(
        config.INTRANET_JOB_API_URL,
        headers=_headers(),
        json={
            "action": "complete",
            "job_id": job_id,
            "task": task,
            "status": status,
            "result": result or {},
            "error": error,
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("error") or "Job completion failed")
