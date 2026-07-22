from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
import subprocess
import tempfile
import shutil

import requests

from order_worker import config


class NoInvoiceDataError(RuntimeError):
    pass


def _filename_from_content_disposition(value: str | None) -> str | None:
    if not value:
        return None

    filename_star = re.search(r"filename\*=UTF-8''([^;]+)", value, flags=re.IGNORECASE)
    if filename_star:
        return unquote(filename_star.group(1).strip().strip('"'))

    filename = re.search(r'filename="?([^";]+)"?', value, flags=re.IGNORECASE)
    if filename:
        return filename.group(1).strip()

    return None


def download_invoice_export(
    site: str,
    export_type: str,
    start_date: str,
    end_date: str,
    *,
    exclude_uploaded: bool = True,
) -> Path:
    path, _row_count = download_invoice_export_with_count(
        site,
        export_type,
        start_date,
        end_date,
        exclude_uploaded=exclude_uploaded,
    )
    return path


def download_invoice_export_with_count(
    site: str,
    export_type: str,
    start_date: str,
    end_date: str,
    *,
    exclude_uploaded: bool = True,
) -> tuple[Path, int | None]:
    config.DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    response = requests.get(
        config.INTRANET_INVOICE_EXPORT_API_URL,
        params={
            "site": site,
            "type": export_type,
            "startDate": start_date,
            "endDate": end_date,
            "excludeUploaded": "1" if exclude_uploaded else "0",
        },
        timeout=90,
    )
    if response.status_code == 404:
        raise NoInvoiceDataError(f"No invoice data for {site} {export_type} {start_date}~{end_date}")
    response.raise_for_status()

    filename = _filename_from_content_disposition(response.headers.get("content-disposition"))
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{timestamp}-{site}-{export_type}-invoice.xls"

    path = config.DOWNLOAD_DIR / Path(filename).name
    path.write_bytes(response.content)
    if site == "special":
        resave_xls_with_excel(path)

    row_count = None
    raw_row_count = response.headers.get("x-invoice-row-count")
    if raw_row_count and raw_row_count.isdigit():
        row_count = int(raw_row_count)
    return path, row_count


def mark_invoice_uploaded(
    site: str,
    export_type: str,
    start_date: str,
    end_date: str,
    failed_order_numbers: list[str] | None = None,
) -> dict:
    response = requests.post(
        config.INTRANET_INVOICE_UPLOAD_MARK_API_URL,
        json={
            "site": site,
            "type": export_type,
            "startDate": start_date,
            "endDate": end_date,
            "failedOrderNumbers": failed_order_numbers or [],
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def resave_xls_with_excel(path: Path) -> None:
    if not path.exists():
        return

    temp_dir = Path(tempfile.mkdtemp(prefix="invoice-xls-"))
    output_path = temp_dir / "resaved.xls"
    script_path = temp_dir / "resave.ps1"
    try:
        script_path.write_text(
            """
param([string]$InputPath, [string]$OutputPath)
$excel = $null
$workbook = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.DisplayAlerts = $false
    $workbook = $excel.Workbooks.Open($InputPath)
    $workbook.SaveAs($OutputPath, 56)
    $workbook.Close($false)
    $excel.Quit()
} finally {
    if ($workbook -ne $null) { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($workbook) | Out-Null }
    if ($excel -ne $null) { [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
""",
            encoding="utf-8",
        )
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                str(path),
                str(output_path),
            ],
            check=True,
            timeout=60,
            capture_output=True,
        )
        shutil.copy2(output_path, path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def parse_ownerclan_result(text: str) -> dict:
    success_count = None
    failed_count = None

    success_match = re.search(r"(\d+)\s*건\s*배송처리\s*성공", text)
    failed_match = re.search(r"(\d+)\s*건\s*배송처리\s*실패", text)
    if success_match:
        success_count = int(success_match.group(1))
    if failed_match:
        failed_count = int(failed_match.group(1))

    failed_orders = re.findall(r"주문번호\s*:\s*([^\s]+).*?배송처리\s*실패\s*\(사유:\s*([^)]+)\)", text)

    result = {
        "success": failed_count in (None, 0),
        "uploadedCount": success_count or 0,
        "failedCount": failed_count or 0,
        "message": "배송정보 등록 결과를 확인했습니다.",
    }
    if failed_orders:
        result["failedOrders"] = [
            {"orderNumber": order_number, "reason": reason}
            for order_number, reason in failed_orders
        ]
    return result


def parse_success_fail_counts(text: str) -> tuple[int | None, int | None]:
    success_count = None
    failed_count = None

    success_match = re.search(r"성공\s*[:：]?\s*([0-9,]+)(?:\s*건)?", text)
    failed_match = re.search(r"실패\s*[:：]?\s*([0-9,]+)(?:\s*건)?", text)
    if success_match:
        success_count = int(success_match.group(1).replace(",", ""))
    if failed_match:
        failed_count = int(failed_match.group(1).replace(",", ""))

    return success_count, failed_count
