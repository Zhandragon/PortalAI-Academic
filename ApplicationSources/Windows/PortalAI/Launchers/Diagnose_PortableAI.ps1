param([switch]$VerboseChecks)
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'Launchers\InstancePorts.ps1') -PortalRoot $Root


$ErrorActionPreference = "SilentlyContinue"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = $ScriptDir
if (-not (Test-Path (Join-Path $Root "Agent"))) {
    $Root = Split-Path -Parent $ScriptDir
}
$Runtime = Join-Path $Root "Agent\.runtime"

function Test-TcpPort {
    param([string]$HostName,[int]$Port,[int]$TimeoutMs=800)
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $ar = $c.BeginConnect($HostName,$Port,$null,$null)
        if (-not $ar.AsyncWaitHandle.WaitOne($TimeoutMs,$false)) { $c.Close(); return $false }
        $c.EndConnect($ar); $c.Close(); return $true
    } catch { return $false }
}

function Test-Http {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
        return [pscustomobject]@{Ok=$true; Status=[int]$r.StatusCode}
    } catch {
        $code = $null
        try { $code=[int]$_.Exception.Response.StatusCode.value__ } catch {}
        return [pscustomobject]@{Ok=$false; Status=$code}
    }
}

function Find-Process {
    param([string[]]$Patterns)
    foreach ($p in (Get-CimInstance Win32_Process)) {
        $s = "$($p.Name) $($p.CommandLine)"
        foreach ($pat in $Patterns) {
            if ($s -match $pat) { return $p }
        }
    }
    return $null
}

function Get-Row {
    param([string]$Name,[int]$Port,[string]$Health,[string[]]$Patterns,[string]$Log="")
    $tcp = Test-TcpPort "127.0.0.1" $Port
    $http = if ($Health) { Test-Http $Health } else { $null }
    $proc = Find-Process $Patterns
    $state =
        if ($http -and $http.Ok) {"READY"}
        elseif ($tcp) {"PORT OPEN"}
        elseif ($proc) {"PROCESS ONLY"}
        else {"STOPPED"}
    [pscustomobject]@{
        Service=$Name
        State=$state
        Port=$Port
        PID=if($proc){$proc.ProcessId}else{""}
        Health=if($http -and $http.Ok){"HTTP $($http.Status)"}elseif($tcp){"listener"}else{""}
        Log=if($Log -and (Test-Path $Log)){$Log}else{""}
    }
}

$qlog = Join-Path $Runtime "qwen_server.log"
$clog = Join-Path $Runtime "comfyui_service.log"
$alog = Join-Path $Runtime "acestep_service.log"

$rows = @(
    (Get-Row "Qwen / llama.cpp" (Get-PortalPort 'qwen') (Get-PortalServiceUrl 'qwen' '/health') @("llama-server\.exe","llama-server") $qlog),
    (Get-Row "ComfyUI" (Get-PortalPort 'comfyui') (Get-PortalServiceUrl 'comfyui' '/system_stats') @("ComfyUI.*main\.py","python.*ComfyUI","run_nvidia_gpu") $clog),
    (Get-Row "ACE-Step API" (Get-PortalPort 'acestep') (Get-PortalServiceUrl 'acestep' '/health') @("ACE-Step","acestep","api_server") $alog),
    (Get-Row "ACE-Step Gradio" 7860 "http://127.0.0.1:7860/" @("ACE-Step","acestep","gradio") "")
)

Write-Host ""
Write-Host "PortableAI quick triage" -ForegroundColor Cyan
Write-Host "Root: $Root"
Write-Host ""
$rows | Format-Table -AutoSize

Write-Host ""
Write-Host "READY = API answered; PORT OPEN = listener exists; PROCESS ONLY = process exists but API is not ready; STOPPED = nothing detected." -ForegroundColor DarkGray

if ($VerboseChecks) {
    foreach ($x in @(
        @{Name="Qwen";Path=$qlog},
        @{Name="ComfyUI";Path=$clog},
        @{Name="ACE-Step";Path=$alog}
    )) {
        Write-Host ""
        Write-Host "---- $($x.Name) recent log ----" -ForegroundColor Yellow
        if (Test-Path $x.Path) { Get-Content $x.Path -Tail 25 } else { Write-Host "No log file." }
    }
}
