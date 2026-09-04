from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from order_worker import config


SITE_MAP = {
    "ownerclan": "ownerclan",
    "Fownerclan": "Fownerclan",
    "onch3": "onch3",
    "onchannel": "onch3",
    "Fonch3": "Fonch3",
    "domeggook": "domeggook",
    "Fdomeggook": "Fdomeggook",
    "specialoffer": "special",
    "special": "special",
    "domesin": "domegod",
    "domegod": "domegod",
    "namdo": "namdo",
}


def _connection_url() -> str:
    if not config.DIRECT_URL:
        raise RuntimeError("DIRECT_URL is required for ORDER_WORKER_TRANSPORT=database.")
    parts = urlsplit(config.DIRECT_URL)
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in {"pgbouncer", "connection_limit"}
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@contextmanager
def connection(*, autocommit: bool = False) -> Iterator[Any]:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("psycopg is required for the local order worker.") from exc
    with psycopg.connect(
        _connection_url(),
        connect_timeout=10,
        autocommit=autocommit,
        row_factory=dict_row,
    ) as database:
        yield database


def claim_run(run_id: str, task_key: str, run_date: str, details: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    from psycopg.types.json import Jsonb

    with connection() as database:
        inserted = database.execute(
            """
            INSERT INTO order_worker_run_history (
                run_id, task_key, run_date, status, details,
                started_at, created_at, updated_at
            ) VALUES (%s, %s, %s, 'started', %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT (run_id) DO NOTHING
            RETURNING *
            """,
            (run_id, task_key, run_date, Jsonb(details)),
        ).fetchone()
        run = inserted or database.execute(
            "SELECT * FROM order_worker_run_history WHERE run_id = %s",
            (run_id,),
        ).fetchone()
        database.commit()
        return inserted is not None, run


def complete_run(run_id: str, status: str, details: dict[str, Any]) -> None:
    from psycopg.types.json import Jsonb

    with connection() as database:
        updated = database.execute(
            """
            UPDATE order_worker_run_history
            SET status = %s, details = %s, completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE run_id = %s
            """,
            (status, Jsonb(details), run_id),
        )
        if updated.rowcount != 1:
            raise RuntimeError("Run not found.")
        database.commit()


def claim_job(job_id: str, task: str) -> tuple[bool, dict[str, Any] | None]:
    with connection() as database:
        job = database.execute(
            """
            UPDATE order_worker_jobs
            SET status = 'running', started_at = COALESCE(started_at, CURRENT_TIMESTAMP),
                error = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid AND task = %s AND status IN ('queued', 'requested')
            RETURNING *
            """,
            (job_id, task),
        ).fetchone()
        acquired = job is not None
        if not job:
            job = database.execute(
                "SELECT * FROM order_worker_jobs WHERE id = %s::uuid AND task = %s",
                (job_id, task),
            ).fetchone()
        database.commit()
        return acquired, job


def is_job_cancelled(job_id: str, task: str) -> bool:
    with connection() as database:
        row = database.execute(
            "SELECT status FROM order_worker_jobs WHERE id = %s::uuid AND task = %s",
            (job_id, task),
        ).fetchone()
    if not row:
        raise RuntimeError("Job not found.")
    return row["status"] == "cancelled"


def update_job_progress(job_id: str, task: str, result: dict[str, Any]) -> None:
    from psycopg.types.json import Jsonb

    with connection() as database:
        updated = database.execute(
            """
            UPDATE order_worker_jobs
            SET result = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid AND task = %s AND status = 'running'
            """,
            (Jsonb(result), job_id, task),
        )
        if updated.rowcount != 1:
            raise RuntimeError("Running job not found.")
        database.commit()


def _registration_sites(result: dict[str, Any]) -> tuple[int, list[str]]:
    request = result.get("request") if isinstance(result.get("request"), dict) else {}
    try:
        product_id = int(request.get("productId") or 0)
    except (TypeError, ValueError):
        product_id = 0
    sites: list[str] = []
    for entry in result.get("summary") if isinstance(result.get("summary"), list) else []:
        if not isinstance(entry, dict) or entry.get("success") is not True or entry.get("preview") is True:
            continue
        site = SITE_MAP.get(str(entry.get("siteCode") or entry.get("site") or ""))
        if site and site not in sites:
            sites.append(site)
    return product_id, sites


def complete_job(job_id: str, task: str, status: str, result: dict[str, Any], error: str | None) -> None:
    from psycopg.types.json import Jsonb

    with connection() as database:
        updated = database.execute(
            """
            UPDATE order_worker_jobs
            SET status = %s, result = %s, error = %s,
                completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s::uuid AND task = %s
              AND status IN ('queued', 'requested', 'running', 'cancelling')
            """,
            (status, Jsonb(result), error, job_id, task),
        )
        if updated.rowcount != 1:
            raise RuntimeError("Job not found.")
        if task == "product-registration":
            product_id, sites = _registration_sites(result)
            for site in sites:
                database.execute(
                    """
                    INSERT INTO intra_product_sites (product_id, site, site_stat, created_at)
                    SELECT %s, %s, '연동', CURRENT_TIMESTAMP
                    WHERE NOT EXISTS (
                        SELECT 1 FROM intra_product_sites WHERE product_id = %s AND site = %s
                    )
                    """,
                    (product_id, site, product_id, site),
                )
        database.commit()


def next_local_job(tasks: tuple[str, ...]) -> dict[str, Any] | None:
    with connection() as database:
        return database.execute(
            """
            SELECT id::text AS id, task
            FROM order_worker_jobs
            WHERE status = 'queued' AND task = ANY(%s)
            ORDER BY requested_at ASC
            LIMIT 1
            """,
            (list(tasks),),
        ).fetchone()
