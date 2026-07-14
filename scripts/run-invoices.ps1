$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$intranetScript = "E:\dev\intranet\scripts\start-intranet-3001.ps1"
$runtimeDir = Join-Path $root "runtime"
$lastRunFile = Join-Path $runtimeDir "invoice-auto-last-date.txt"
$today = Get-Date -Format "yyyy-MM-dd"

function Test-PortOpen {
    param([int]$Port)

    try {
        $client = [System.Net.Sockets.TcpClient]::new()
        $async = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $connected = $async.AsyncWaitHandle.WaitOne(700)
        if ($connected) {
            $client.EndConnect($async)
        }
        $client.Close()
        return $connected
    } catch {
        return $false
    }
}

if (-not (Test-Path -LiteralPath $python)) {
    $python = "python"
}

New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
if ((Test-Path -LiteralPath $lastRunFile) -and ((Get-Content -Raw -LiteralPath $lastRunFile).Trim() -eq $today)) {
    Write-Host "Invoice auto upload already started today: $today"
    exit 0
}

# Mark before execution so the scheduled job can never start a second automatic
# real/fake upload on the same calendar day.
Set-Content -LiteralPath $lastRunFile -Value $today -Encoding UTF8

if (-not (Test-PortOpen -Port 3001) -and (Test-Path -LiteralPath $intranetScript)) {
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", $intranetScript `
        -WorkingDirectory "E:\dev\intranet" `
        -WindowStyle Hidden

    $deadline = (Get-Date).AddSeconds(90)
    while (-not (Test-PortOpen -Port 3001) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
    }
}

if (-not (Test-PortOpen -Port 3001)) {
    throw "Intranet API server did not start on port 3001."
}

Set-Location $root
$failedTypes = @()
foreach ($invoiceType in @("real", "fake")) {
    Write-Host "Starting automatic invoice upload: $invoiceType"
    & $python -m order_worker.main upload-invoices --all --type $invoiceType
    if ($LASTEXITCODE -ne 0) {
        $failedTypes += $invoiceType
    }
}

if ($failedTypes.Count -gt 0) {
    throw "Invoice upload failed: $($failedTypes -join ', ')"
}
