param(
  [int]$Port = 8765
)
$ErrorActionPreference = 'Continue'
$conn = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
if (-not $conn) { "not listening on $Port"; exit 0 }
foreach ($procId in ($conn.OwningProcess | Select-Object -Unique)) {
  $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId"
  if ($p.CommandLine -match 'emotioncore-service[\\/]server\.py') {
    "stopping pid=$procId"
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
  } else {
    "skip pid=$procId (not emotioncore service): $($p.CommandLine)"
  }
}
