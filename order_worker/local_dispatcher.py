from __future__ import annotations

import asyncio
import logging
import os
import time

from order_worker import config, database_transport
from order_worker.lock import WorkerLock
from order_worker.main import run_job_command


DEFAULT_LOCAL_TASKS = ("product-status", "product-registration", "product-edit")


def local_tasks() -> tuple[str, ...]:
    configured = os.getenv("ORDER_WORKER_LOCAL_TASKS", "").strip()
    if not configured:
        return DEFAULT_LOCAL_TASKS
    return tuple(dict.fromkeys(item.strip() for item in configured.split(",") if item.strip()))


def wait_for_wakeup(timeout: int) -> None:
    try:
        with database_transport.connection(autocommit=True) as database:
            database.execute("LISTEN order_worker_jobs")
            for _notification in database.notifies(timeout=timeout, stop_after=1):
                return
    except Exception as exc:
        logging.warning("order worker notification wait failed; using fallback timer: %s", exc)
        time.sleep(min(timeout, 15))


async def dispatch_forever() -> None:
    tasks = local_tasks()
    if not tasks:
        raise RuntimeError("ORDER_WORKER_LOCAL_TASKS is empty.")
    config.ORDER_WORKER_TRANSPORT = "database"
    logging.info("local order dispatcher started tasks=%s", ",".join(tasks))
    while True:
        try:
            job = await asyncio.to_thread(database_transport.next_local_job, tasks)
            if not job:
                await asyncio.to_thread(wait_for_wakeup, config.ORDER_WORKER_LOCAL_POLL_SECONDS)
                continue
            config.ORDER_WORKER_JOB_ID = str(job["id"])
            task = str(job["task"])
            logging.info("starting local order job id=%s task=%s", config.ORDER_WORKER_JOB_ID, task)
            exit_code = await run_job_command(task)
            logging.info("local order job finished id=%s task=%s exit=%s", config.ORDER_WORKER_JOB_ID, task, exit_code)
        except KeyboardInterrupt:
            return
        except Exception:
            logging.exception("local order dispatcher loop failed")
            await asyncio.sleep(15)


def main() -> int:
    config.ensure_directories()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(config.LOG_DIR / "local-dispatcher.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    lock_path = config.RUNTIME_DIR / "order-worker-local-dispatcher.lock"
    with WorkerLock(lock_path):
        asyncio.run(dispatch_forever())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
