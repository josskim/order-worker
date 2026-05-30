from __future__ import annotations

import requests

from order_worker import config


def shorten(value: object, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def send_telegram_message(message: str) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("PROGRESS: [telegram] settings missing. notification skipped.")
        return

    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message[:3500],
    }
    requests.post(url, json=payload, timeout=10).raise_for_status()


def build_summary_message(results: list[dict], run_id: str) -> str:
    failed = [item for item in results if not item.get("success")]
    title = "부분 실패" if failed else "성공"
    lines = [f"[자동 주문서 수집] {title}", f"ID: {run_id}", ""]

    for item in results:
        site = item.get("site", "?")
        if not item.get("success"):
            error = shorten(item.get("error", "알 수 없는 오류"))
            lines.append(f"실패 - {site}: {error}")
            continue

        total = item.get("totalRows", 0)
        inserted = item.get("insertedCount", 0)
        duplicate = item.get("duplicateCount", 0)
        if total == 0:
            lines.append(f"성공 - {site}: 주문 없음")
        else:
            lines.append(f"성공 - {site}: 등록 {inserted}건 / 중복 {duplicate}건")

    return "\n".join(lines)[:3500]
