$ErrorActionPreference = "Stop"

$workerRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $workerRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "order-worker virtual environment was not found: $pythonPath"
}

$env:ORDER_WORKER_TRANSPORT = "database"
$env:ORDER_WORKER_LOCAL_TASKS = "product-status,product-registration,product-edit"
$env:ORDER_WORKER_LOCAL_POLL_SECONDS = "60"

Set-Location $workerRoot
& $pythonPath -m order_worker.local_dispatcher
