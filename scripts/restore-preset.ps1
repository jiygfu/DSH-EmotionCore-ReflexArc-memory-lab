# Restore the full qq-chat-v2 preset after a failed trim test.
# Run from the SoulCore repo root.
$ErrorActionPreference = 'Stop'
$src = Join-Path ($env:SURFCORE_ROOT ?? (Join-Path $env:USERPROFILE 'surfcore')) 'dsh\agent-presets\qq-chat-v2\agent.cordis.yml'
$bak = Join-Path $PSScriptRoot '..\backups\qq-chat-v2-before-trim-20261031.yml'
if (-not (Test-Path $bak)) { throw "backup not found: $bak" }
Copy-Item $bak $src -Force
Write-Host "restored $src"
Write-Host "Restart DSH (not just the bridge) for the preset to take effect."
