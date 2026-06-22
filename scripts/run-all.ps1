$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$intranetScript = "E:\dev\intranet\scripts\start-intranet-3001.ps1"

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

if (-not (Test-Path $python)) {
    $python = "python"
}

if (-not (Test-PortOpen -Port 3001) -and (Test-Path $intranetScript)) {
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
& $python -m order_worker.main run --all
