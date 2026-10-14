from __future__ import annotations

import asyncio
import json
import os
import subprocess
from pathlib import Path
from typing import Any

from order_worker import config


async def run_account(request: dict[str, Any], account: dict[str, Any], preview: bool = False) -> dict[str, Any]:
    site = str(account.get("siteCode") or "")
    base = {"site": "조원" if site == "account1" else "마법바지", "siteCode": site, "productCode": request.get("productCode")}
    root = Path(os.environ.get("SINSANG_WORKER_ROOT", str(config.PROJECT_ROOT.parent / "sinsang")))
    python = root / ".venv" / "Scripts" / "python.exe"
    script = config.PROJECT_ROOT / "scripts" / "sinsang-batch-registration.py"
    if not python.exists():
        return {**base, "success": False, "error": "신상마켓 로컬 워커 실행환경을 찾지 못했습니다."}
    process = await asyncio.create_subprocess_exec(
        str(python), str(script), str(root),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=str(root), env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    try:
        output, error = await asyncio.wait_for(process.communicate(json.dumps({"request": request, "account": account, "preview": preview}, ensure_ascii=False).encode("utf-8")), timeout=900)
        lines = output.decode("utf-8", errors="replace").splitlines()
        for line in lines:
            if line.startswith("BATCH_RESULT:"):
                return {**base, **json.loads(line.removeprefix("BATCH_RESULT:"))}
            if line.startswith("PROGRESS:"):
                print(line, flush=True)
        return {**base, "success": False, "error": error.decode("utf-8", errors="replace")[-800:] or "신상마켓 등록 결과를 받지 못했습니다."}
    except BaseException as exc:
        if process.returncode is None:
            if os.name == "nt":
                await asyncio.to_thread(subprocess.run, ["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                process.kill()
        await process.wait()
        if isinstance(exc, Exception):
            return {**base, "success": False, "error": "신상마켓 등록 제한시간 초과" if isinstance(exc, asyncio.TimeoutError) else str(exc)}
        raise
