param([string]$PortableAIRoot = "")
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'Launchers\InstancePorts.ps1') -PortalRoot $Root


$ErrorActionPreference = "Stop"

# Check VM availability before starting a model or opening the host gateway.
if (-not (Get-Command WindowsSandbox.exe -ErrorAction SilentlyContinue)) {
    throw "Secure Agent requires Windows Sandbox (supported Windows Pro/Enterprise/Education with the feature enabled). This host cannot run that VM backend. Full-access mode remains available."
}

function Quote-ProcessArg([string]$Value) {
    if ($null -eq $Value) { return '""' }
    # Windows PowerShell 5.1's Start-Process joins ArgumentList into one command
    # line. Paths containing spaces therefore MUST be quoted explicitly.
    return '"' + ($Value -replace '"', '\"') + '"'
}

function Show-LogTail([string]$Path, [int]$Lines = 20) {
    if (Test-Path $Path) {
        Write-Host ""
        Write-Host "---- log tail: $Path ----"
        Get-Content $Path -Tail $Lines -ErrorAction SilentlyContinue
        Write-Host "--------------------------"
    }
}

if ($PortableAIRoot) {
    $Root = (Resolve-Path $PortableAIRoot).Path
} else {
    $known = "$(Split-Path -Parent $PSScriptRoot)"
    if (Test-Path (Join-Path $known "LLM\llamacpp\llama-server.exe")) {
        $Root = $known
    } else {
        throw "PortableAI root not found. Pass -PortableAIRoot."
    }
}

$LLama = Join-Path $Root "LLM\llamacpp\llama-server.exe"
$Model = Join-Path $Root "LLM\models\Qwen3.8-27B-Q4_K_M.gguf"
$Mmproj = Join-Path $Root "LLM\models\mmproj-Qwen3.8-27B-Standard-BF16.gguf"
$Security = Join-Path $Root "Sandbox\Security"
$GatewayPy = Join-Path $Security "secure_agent_gateway.py"
$TokenFile = Join-Path $Security "agent_token.txt"
$Wsb = Join-Path $Security "PortableAI_Secure_Agent.wsb"
$Runtime = Join-Path $Root "Agent\.runtime"

New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

foreach ($p in @($LLama, $Model, $Mmproj, $GatewayPy, $TokenFile, $Wsb)) {
    if (-not (Test-Path $p)) {
        throw "Required file missing: $p"
    }
}

[xml]$sandboxConfig = Get-Content -LiteralPath $Wsb -Raw
foreach ($mapping in $sandboxConfig.Configuration.MappedFolders.MappedFolder) {
    if (-not (Test-Path -LiteralPath $mapping.HostFolder)) {
        throw "Secure Agent mapping points to a missing host path. The legacy VM configuration must be rebuilt for this portable location before use."
    }
    if (([IO.Path]::GetFullPath($mapping.HostFolder).TrimEnd('\') -eq $Root.TrimEnd('\')) -and $mapping.ReadOnly -ne 'true') {
        throw "Secure Agent refused: the legacy VM maps the entire application writable. Use an isolated workspace and read-only application mappings before enabling this mode."
    }
}


# ---------------------------------------------------------------------------
# 0. Validate the shared gateway token BEFORE consuming GPU resources.
# ---------------------------------------------------------------------------
function Test-ReadableToken([string]$Path) {
    try {
        $value = (Get-Content -LiteralPath $Path -Raw -ErrorAction Stop).Trim()
        return ($value.Length -ge 32)
    } catch {
        return $false
    }
}

if (-not (Test-ReadableToken $TokenFile)) {
    Write-Warning "The Secure Agent token is not readable. Attempting to restore inherited ACLs..."
    try {
        # On this Windows build, /inheritance and /reset cannot be combined
        # in one icacls invocation. Run them separately.
        & icacls.exe $TokenFile /inheritance:e | Out-Null
        if ($LASTEXITCODE -eq 0) {
            & icacls.exe $TokenFile /reset | Out-Null
        }
    } catch {}

    if (-not (Test-ReadableToken $TokenFile)) {
        throw @"
The Secure Agent token still cannot be read:
  $TokenFile

This is the leftover ACL problem from v15.48-v15.51.

Run this package's:
  Repair_Secure_Agent_Token_Permissions.bat

as Administrator, then run Start_Secure_Agent.bat again.
"@
    }
    Write-Host "[OK] Token permissions repaired."
} else {
    Write-Host "[OK] Secure Agent token is readable."
}

# ---------------------------------------------------------------------------
# 1. Qwen on host loopback only
# ---------------------------------------------------------------------------
$qwenListener = Get-NetTCPConnection -LocalPort (Get-PortalPort 'qwen') -State Listen -ErrorAction SilentlyContinue

if (-not $qwenListener) {
    Write-Host "[START] Qwen / llama.cpp on host loopback..."

    $qwenStdout = Join-Path $Runtime "secure_qwen.stdout.log"
    $qwenStderr = Join-Path $Runtime "secure_qwen.stderr.log"

    Remove-Item $qwenStdout,$qwenStderr -Force -ErrorAction SilentlyContinue

    # Explicit quoting is required because the real PortableAI path contains
    # "Offline AI".
    $qwenArgs = @(
        "-m", (Quote-ProcessArg $Model),
        "--mmproj", (Quote-ProcessArg $Mmproj),
        "-ngl", "999",
        "-c", "16384",
        "--no-mmproj-offload",
        "--host", "127.0.0.1",
        "--port", (Get-PortalPort 'qwen')
    )

    $qwenProc = Start-Process `
        -FilePath $LLama `
        -ArgumentList $qwenArgs `
        -WorkingDirectory $Root `
        -RedirectStandardOutput $qwenStdout `
        -RedirectStandardError $qwenStderr `
        -PassThru

    Set-Content -Encoding ASCII -Path (Join-Path $Runtime "secure_qwen.pid") -Value $qwenProc.Id

    $deadline = (Get-Date).AddMinutes(5)
    $ready = $false

    while ((Get-Date) -lt $deadline) {
        # Fail fast if llama-server has already crashed.
        $qwenProc.Refresh()
        if ($qwenProc.HasExited) {
            Show-LogTail $qwenStdout
            Show-LogTail $qwenStderr
            throw "Qwen exited during startup with code $($qwenProc.ExitCode)."
        }

        try {
            $r = Invoke-RestMethod `
                -Uri (Get-PortalServiceUrl 'qwen' '/v1/models') `
                -TimeoutSec 3 `
                -ErrorAction Stop
            if ($r) {
                $ready = $true
                break
            }
        } catch {}

        Start-Sleep -Milliseconds 750
    }

    if (-not $ready) {
        Show-LogTail $qwenStdout
        Show-LogTail $qwenStderr
        throw "Qwen did not become ready within 5 minutes."
    }
}

Write-Host "[OK] Qwen is host-only on 127.0.0.1:8080"

# ---------------------------------------------------------------------------
# 2. Authenticated gateway
# ---------------------------------------------------------------------------
$gatewayListener = Get-NetTCPConnection -LocalPort (Get-PortalPort 'gateway') -State Listen -ErrorAction SilentlyContinue

if (-not $gatewayListener) {
    Write-Host "[START] Secure Agent Gateway..."

    $python = Join-Path $Root "Runtime\BootstrapPython\python.exe"
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Bundled BootstrapPython is missing. Repair the portable runtime."
    }

    $gatewayStdout = Join-Path $Runtime "secure_agent_gateway.stdout.log"
    $gatewayStderr = Join-Path $Runtime "secure_agent_gateway.stderr.log"

    Remove-Item $gatewayStdout,$gatewayStderr -Force -ErrorAction SilentlyContinue

    $gatewayArgs = @(
        "-u",
        (Quote-ProcessArg $GatewayPy),
        "--root", (Quote-ProcessArg $Root),
        "--bind", "0.0.0.0",
        "--port", (Get-PortalPort 'gateway'),
        "--qwen-host", "127.0.0.1",
        "--qwen-port", (Get-PortalPort 'qwen'),
        "--token-file", (Quote-ProcessArg $TokenFile)
    )

    $gatewayProc = Start-Process `
        -FilePath $python `
        -ArgumentList $gatewayArgs `
        -WorkingDirectory $Root `
        -WindowStyle Hidden `
        -RedirectStandardOutput $gatewayStdout `
        -RedirectStandardError $gatewayStderr `
        -PassThru

    Set-Content -Encoding ASCII -Path (Join-Path $Runtime "secure_agent_gateway.pid") -Value $gatewayProc.Id

    $deadline = (Get-Date).AddSeconds(30)
    $gatewayReady = $false

    while ((Get-Date) -lt $deadline) {
        $gatewayProc.Refresh()
        if ($gatewayProc.HasExited) {
            Show-LogTail $gatewayStdout
            Show-LogTail $gatewayStderr
            throw "Secure gateway exited during startup with code $($gatewayProc.ExitCode)."
        }

        $listen = Get-NetTCPConnection -LocalPort (Get-PortalPort 'gateway') -State Listen -ErrorAction SilentlyContinue
        if ($listen) {
            $gatewayReady = $true
            break
        }
        Start-Sleep -Milliseconds 300
    }

    if (-not $gatewayReady) {
        Show-LogTail $gatewayStdout
        Show-LogTail $gatewayStderr
        throw "Secure gateway did not begin listening on port 18080."
    }
}

Write-Host "[OK] Authenticated Secure Agent Gateway is listening on port 18080"

# ---------------------------------------------------------------------------
# 3. Launch disposable desktop-agent environment
# ---------------------------------------------------------------------------
Write-Host "[START] Windows Sandbox..."
Start-Process -FilePath $Wsb

Write-Host ""
Write-Host "============================================================"
Write-Host "PortableAI Secure Agent is running"
Write-Host "============================================================"
Write-Host "Qwen brain:       RTX 4090 host / 127.0.0.1:8080"
Write-Host "Secure gateway:   port 18080"
Write-Host "Agent desktop:    Windows Sandbox"
Write-Host "Host RW exposure: PortableAI folder only"
Write-Host "============================================================"
