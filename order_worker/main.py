from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime

import requests

from order_worker import config
from order_worker.lock import WorkerLock
from order_worker.notifier import build_summary_message, send_telegram_message
from order_worker.sites import domeggook, domesin, onchannel, ownerclan, specialoffer


SITE_RUNNERS = {
    "ownerclan": ownerclan.run,
    "onchannel": onchannel.run,
    "domeggook": domeggook.run,
    "specialoffer": specialoffer.run,
    "domesin": domesin.run,
}


def format_result(result: dict) -> str:
    site = result.get("site", "?")
    if not result.get("success"):
        return f"[FAIL] {site}: {result.get('error', 'unknown error')}"
    if result.get("totalRows", 0) == 0:
        return f"[EMPTY] {site}: no orders"
    return f"[OK] {site}: inserted {result.get('insertedCount', 0)}, duplicate {result.get('duplicateCount', 0)}"


def cleanup_downloads() -> None:
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for path in config.DOWNLOAD_DIR.iterdir():
        if path.is_file():
            path.unlink(missing_ok=True)


async def run_sites(site_names: list[str]) -> list[dict]:
    results: list[dict] = []
    cleanup_downloads()

    for site_name in site_names:
        runner = SITE_RUNNERS[site_name]
        print(f"PROGRESS: [{site_name}] start")
        try:
            site_results = await runner()
            results.extend(site_results)
        except Exception as exc:
            results.append({"site": site_name, "success": False, "error": str(exc)})

    cleanup_downloads()
    return results


def write_log(run_id: str, results: list[dict]) -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "runId": run_id,
        "createdAt": datetime.now().isoformat(timespec="seconds"),
        "results": results,
    }
    path = config.LOG_DIR / f"run-{run_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def post_intranet_log(run_id: str, results: list[dict]) -> None:
    try:
        requests.post(config.INTRANET_LOG_API_URL, json={"run_id": run_id, "summary": results}, timeout=10)
    except Exception as exc:
        print(f"PROGRESS: [log] intranet log failed: {exc}")


async def run_command(args: argparse.Namespace) -> int:
    config.ensure_directories()
    site_names = list(SITE_RUNNERS.keys()) if args.all else args.site
    run_id = str(uuid.uuid4())[:8]

    with WorkerLock(config.LOCK_FILE):
        print(f"PROGRESS: [worker] run_id={run_id}")
        results = await run_sites(site_names)

    for result in results:
        print(format_result(result))

    write_log(run_id, results)
    post_intranet_log(run_id, results)

    try:
        send_telegram_message(build_summary_message(results, run_id))
    except Exception as exc:
        print(f"PROGRESS: [telegram] send failed: {exc}")

    print("__JSON__")
    print(json.dumps(results, ensure_ascii=False))
    return 1 if any(not item.get("success") for item in results) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="order-worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run order collection")
    group = run_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Run all sites")
    group.add_argument("--site", action="append", choices=sorted(SITE_RUNNERS.keys()), help="Run selected site")

    subparsers.add_parser("sites", help="List supported sites")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "sites":
        for site_name in SITE_RUNNERS:
            print(site_name)
        return 0

    if args.command == "run":
        return asyncio.run(run_command(args))

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

