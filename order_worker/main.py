from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime

import requests

from order_worker import config
from order_worker.lock import WorkerLock
from order_worker.notifier import build_invoice_upload_summary_message, build_summary_message, send_telegram_message
from order_worker.sites import (
    domeggook,
    domeggook_invoice,
    domesin,
    domesin_invoice,
    onchannel,
    onchannel_invoice,
    ownerclan,
    ownerclan_invoice,
    sister,
    sister_invoice,
    specialoffer,
    specialoffer_invoice,
)
from order_worker.sites.invoice_utils import mark_invoice_uploaded


SITE_RUNNERS = {
    "ownerclan": ownerclan.run,
    "onchannel": onchannel.run,
    "domeggook": domeggook.run,
    "specialoffer": specialoffer.run,
    "domesin": domesin.run,
    "sister": sister.run,
}

INVOICE_UPLOAD_SITES = {
    "ownerclan": "오너클랜",
    "Fownerclan": "F오너클랜",
    "onch3": "온채널",
    "Fonch3": "F온채널",
    "domeggook": "도매꾹",
    "Fdomeggook": "F도매꾹",
    "domegod": "도매의신",
    "special": "스페셜오퍼",
}

INVOICE_UPLOAD_SITES["sister"] = "시스터"

OWNERCLAN_INVOICE_SITES = {"ownerclan", "Fownerclan"}
ONCHANNEL_INVOICE_SITES = {"onch3", "Fonch3"}
DOMEGGOOK_INVOICE_SITES = {"domeggook", "Fdomeggook"}
DOMESIN_INVOICE_SITES = {"domegod"}
SPECIALOFFER_INVOICE_SITES = {"special"}
SISTER_INVOICE_SITES = {"sister"}


def format_result(result: dict) -> str:
    site = result.get("site", "?")
    if not result.get("success"):
        return f"[FAIL] {site}: {result.get('error', 'unknown error')}"
    if result.get("totalRows", 0) == 0:
        return f"[EMPTY] {site}: no orders"
    return f"[OK] {site}: inserted {result.get('insertedCount', 0)}, duplicate {result.get('duplicateCount', 0)}"


def format_invoice_upload_result(result: dict) -> str:
    site = result.get("site", "?")
    if not result.get("success"):
        prefix = "STOP" if result.get("cancelRequest") else "FAIL"
        return f"[{prefix}] {site}: {result.get('error') or result.get('message') or 'unknown error'}"
    return f"[OK] {site}: uploaded {result.get('uploadedCount', 0)}, failed {result.get('failedCount', 0)}"


def normalize_invoice_no_data_results(results: list[dict]) -> None:
    for result in results:
        error = str(result.get("error") or "")
        if error.startswith("No invoice data for "):
            result["success"] = True
            result["uploadedCount"] = 0
            result["failedCount"] = 0
            result["noData"] = True
            result["message"] = "업로드할 송장 데이터가 없습니다."
            result.pop("error", None)


def mark_successful_invoice_uploads(results: list[dict], export_type: str, start_date: str, end_date: str) -> None:
    for result in results:
        if not result.get("success") or result.get("preview") or result.get("noData"):
            continue
        if int(result.get("uploadedCount") or 0) <= 0:
            continue
        site_code = result.get("siteCode")
        if not site_code:
            continue
        failed_order_numbers = [
            str(item.get("orderNumber") or "")
            for item in result.get("failedOrders", [])
            if item.get("orderNumber")
        ]
        try:
            mark_result = mark_invoice_uploaded(site_code, export_type, start_date, end_date, failed_order_numbers)
            result["markedUploadedCount"] = mark_result.get("markedCount", 0)
        except Exception as exc:
            result["markUploadedError"] = str(exc)


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


async def upload_invoices_command(args: argparse.Namespace) -> int:
    config.ensure_directories()
    site_names = list(INVOICE_UPLOAD_SITES.keys()) if args.all else args.site
    today = datetime.now().strftime("%Y-%m-%d")
    start_date = args.start_date or today
    end_date = args.end_date or start_date
    run_id = str(uuid.uuid4())[:8]

    with WorkerLock(config.LOCK_FILE):
        print(
            f"PROGRESS: [invoice-upload] run_id={run_id}, type={args.type}, "
            f"date={start_date}~{end_date}, preview={args.preview}"
        )
        results = []
        ownerclan_sites = [site for site in site_names if site in OWNERCLAN_INVOICE_SITES]
        onchannel_sites = [site for site in site_names if site in ONCHANNEL_INVOICE_SITES]
        domeggook_sites = [site for site in site_names if site in DOMEGGOOK_INVOICE_SITES]
        domesin_sites = [site for site in site_names if site in DOMESIN_INVOICE_SITES]
        specialoffer_sites = [site for site in site_names if site in SPECIALOFFER_INVOICE_SITES]
        sister_sites = [site for site in site_names if site in SISTER_INVOICE_SITES]
        if ownerclan_sites:
            results.extend(
                await ownerclan_invoice.run(ownerclan_sites, args.type, start_date, end_date, preview=args.preview)
            )
        if onchannel_sites:
            results.extend(
                await onchannel_invoice.run(onchannel_sites, args.type, start_date, end_date, preview=args.preview)
            )
        if domeggook_sites:
            results.extend(
                await domeggook_invoice.run(domeggook_sites, args.type, start_date, end_date, preview=args.preview)
            )
        if domesin_sites:
            results.extend(
                await domesin_invoice.run(domesin_sites, args.type, start_date, end_date, preview=args.preview)
            )
        if specialoffer_sites:
            results.extend(
                await specialoffer_invoice.run(specialoffer_sites, args.type, start_date, end_date, preview=args.preview)
            )
        if sister_sites:
            results.extend(
                await sister_invoice.run(sister_sites, args.type, start_date, end_date, preview=args.preview)
            )

    normalize_invoice_no_data_results(results)
    if not args.preview:
        mark_successful_invoice_uploads(results, args.type, start_date, end_date)

    for result in results:
        print(format_invoice_upload_result(result))

    write_log(f"invoice-upload-{run_id}", results)
    try:
        send_telegram_message(build_invoice_upload_summary_message(results, run_id))
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

    invoice_parser = subparsers.add_parser("upload-invoices", help="Upload invoice Excel files to vendor sites")
    invoice_group = invoice_parser.add_mutually_exclusive_group(required=True)
    invoice_group.add_argument("--all", action="store_true", help="Run all supported invoice upload sites")
    invoice_group.add_argument("--site", action="append", choices=sorted(INVOICE_UPLOAD_SITES.keys()), help="Run selected site")
    invoice_parser.add_argument("--type", choices=["real", "fake"], default="real", help="Invoice export type")
    invoice_parser.add_argument("--start-date", help="Start date in YYYY-MM-DD. Defaults to today.")
    invoice_parser.add_argument("--end-date", help="End date in YYYY-MM-DD. Defaults to start date.")
    invoice_parser.add_argument("--preview", action="store_true", help="Upload Excel and stop before final shipping registration.")

    subparsers.add_parser("sites", help="List supported sites")
    subparsers.add_parser("invoice-sites", help="List supported invoice upload sites")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "sites":
        for site_name in SITE_RUNNERS:
            print(site_name)
        return 0

    if args.command == "invoice-sites":
        for site_name, label in INVOICE_UPLOAD_SITES.items():
            print(f"{site_name}\t{label}")
        return 0

    if args.command == "run":
        return asyncio.run(run_command(args))

    if args.command == "upload-invoices":
        return asyncio.run(upload_invoices_command(args))

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
