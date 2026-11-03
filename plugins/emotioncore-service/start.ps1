param(
  [int]$Port = 8765
)
$ErrorActionPreference = 'Continue'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$script = Join-Path $PSScriptRoot 'server.py'
$py = if ($env:SOULCORE_PYTHON) { $env:SOULCORE_PYTHON } else { 'python' }
$logDir = Join-Path $root 'logs'
New-Item -ItemType Directory -Force $logDir | Out-Null
$running = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if ($running) {
  "EmotionCore already listening on $Port (pid=$($running.OwningProcess -join ','))"
  exit 0
}
$out = Join-Path $logDir 'emotioncore-service.out.log'
$err = Join-Path $logDir 'emotioncore-service.err.log'
$p = Start-Process -FilePath $py -ArgumentList @($script, '--port', "$Port") -WorkingDirectory $root -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err -PassThru
"started pid=$($p.Id) port=$Port"
Start-Sleep -Seconds 2
try {
  $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
  "health=$($r | ConvertTo-Json -Compress)"
} catch {
  "health failed: $($_.Exception.Message)"
  if (Test-Path $err) { Get-Content $err -Tail 20 }
}
