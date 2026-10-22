param([string]$PortableAIRoot = "")
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'Launchers\InstancePorts.ps1') -PortalRoot $Root

$ErrorActionPreference = "Stop"

$Root = $PortableAIRoot
if (-not $Root) { $Root = "C:\Users\genes\OneDrive\Desktop\Offline AI\PortableAI" }
$Token = (Get-Content (Join-Path $Root "Sandbox\Security\agent_token.txt") -Raw).Trim()
$Headers = @{ Authorization = "Bearer $Token"; "Content-Type" = "application/json" }

Write-Host "[1/3] Health..."
$h = Invoke-RestMethod -Uri (Get-PortalServiceUrl 'gateway' '/portableai/health') -Headers $Headers
if (-not $h.ok) { throw "Gateway health failed." }
Write-Host "  OK"

Write-Host "[2/3] Verify there is no shell endpoint..."
try {
    Invoke-RestMethod `
      -Method Post `
      -Uri (Get-PortalServiceUrl 'gateway' '/portableai/run') `
      -Headers $Headers `
      -Body (@{kind="shell";args=@("whoami")} | ConvertTo-Json)
    throw "FAIL: shell kind unexpectedly succeeded."
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 403) {
        Write-Host "  OK: arbitrary host shell denied"
    } else {
        throw
    }
}

Write-Host "[3/3] Verify outside-root path is rejected..."
$body = @{
    kind = "ai"
    args = @("preview", "C:\Windows\System32\drivers\etc\hosts")
} | ConvertTo-Json
try {
    Invoke-RestMethod `
      -Method Post `
      -Uri (Get-PortalServiceUrl 'gateway' '/portableai/run') `
      -Headers $Headers `
      -Body $body
    throw "FAIL: outside-root path unexpectedly succeeded."
} catch {
    if ($_.Exception.Response.StatusCode.value__ -eq 403) {
        Write-Host "  OK: outside-PortableAI host path denied"
    } else {
        throw
    }
}

Write-Host ""
Write-Host "SECURITY SELF-TEST PASSED"
