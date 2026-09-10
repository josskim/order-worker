param([ValidateSet('inspect','kill','start')][string]$Action='inspect')
$ErrorActionPreference='Stop'
$workerRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workerRoot '.venv\Scripts\python.exe'
$all = @(Get-CimInstance Win32_Process)
$matches = @($all | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'order_worker\.local_dispatcher' -and $_.CommandLine.Contains($python) })
$ids = @($matches | ForEach-Object { [int]$_.ProcessId })
$roots = @($matches | Where-Object { [int]$_.ParentProcessId -notin $ids })
if ($Action -eq 'kill') {
    foreach ($worker in $roots) {
        & taskkill.exe /PID $worker.ProcessId /T /F | Out-Null
        if ($LASTEXITCODE -ne 0 -and (Get-Process -Id $worker.ProcessId -ErrorAction SilentlyContinue)) { throw 'Verified order-worker process did not stop.' }
    }
}
if ($Action -eq 'start' -and !$roots.Count) {
    $env:ORDER_WORKER_TRANSPORT='database'
    $env:ORDER_WORKER_LOCAL_TASKS='product-status,product-registration,product-edit,collect,invoices-real,invoices-fake'
    $env:ORDER_WORKER_LOCAL_POLL_SECONDS='30'
    Start-Process -FilePath $python -ArgumentList @('-m','order_worker.local_dispatcher') -WorkingDirectory $workerRoot -WindowStyle Hidden | Out-Null
}
ConvertTo-Json -Compress -InputObject @($roots | ForEach-Object {[int]$_.ProcessId})
