param([string]$PortableAIRoot = "")
$ErrorActionPreference = "SilentlyContinue"

$Root = $PortableAIRoot
if (-not $Root) { $Root = "$(Split-Path -Parent $PSScriptRoot)" }
$pidFile = Join-Path $Root "Agent\.runtime\secure_agent_gateway.pid"
if (Test-Path $pidFile) {
    $pidValue = (Get-Content $pidFile -Raw).Trim()
    if ($pidValue -match '^\d+$') {
        Stop-Process -Id ([int]$pidValue) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}
Write-Host "Secure gateway stopped. Qwen was intentionally left running."
