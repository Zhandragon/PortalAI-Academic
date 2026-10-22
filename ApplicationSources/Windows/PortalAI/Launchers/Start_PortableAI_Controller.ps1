param(
    [Parameter(Mandatory=$true)]
    [string]$Root
)
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'Launchers\InstancePorts.ps1') -PortalRoot $Root


$ErrorActionPreference = 'Stop'
$Root = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
$runtime = Join-Path $Root 'Agent\.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$log = Join-Path $runtime 'portableai_launcher.log'

function Log([string]$Message) {
    try { Add-Content -LiteralPath $log -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $Message) -Encoding UTF8 } catch {}
}

function Fail([string]$Message) {
    Log ('ERROR: ' + $Message)
    try {
        Add-Type -AssemblyName PresentationFramework -ErrorAction SilentlyContinue
        [System.Windows.MessageBox]::Show($Message + "`n`nSee:`n" + $log, 'PortableAI startup error') | Out-Null
    } catch {}
    exit 1
}

function Test-Port([int]$Port) {
    try { return $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1) }
    catch { return $false }
}

function Start-HiddenPowerShell([string]$Script, [string[]]$Arguments) {
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $all = @('-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',('"' + $Script + '"')) + $Arguments
    $psi.Arguments = ($all -join ' ')
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    return [System.Diagnostics.Process]::Start($psi)
}

$llama = Join-Path $Root 'LLM\llamacpp\llama-server.exe'
$model = Join-Path $Root 'LLM\models\Qwen3.8-27B-Q4_K_M.gguf'
$mmproj = Join-Path $Root 'LLM\models\mmproj-Qwen3.8-27B-Standard-BF16.gguf'
$qwenHelper = Join-Path $Root 'Launchers\Start_Qwen_Hidden.ps1'
foreach ($p in @($llama,$model,$mmproj,$qwenHelper)) {
    if (-not (Test-Path -LiteralPath $p)) { Fail ('Required file missing: ' + $p) }
}

Log 'Starting PortableAI session.'
if (-not (Test-Port (Get-PortalPort 'qwen'))) {
    Log 'Starting hidden Qwen server.'
    & $qwenHelper -Root $Root -GpuLayers 32 -IdleSleep 300 -Context 32768

    $deadline = (Get-Date).AddMinutes(5)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-RestMethod -Uri (Get-PortalServiceUrl 'qwen' '/v1/models') -TimeoutSec 3
            if ($r) { $ready = $true; break }
        } catch {}
        Start-Sleep -Seconds 2
    }
    if (-not $ready) { Fail 'Qwen did not become ready within 5 minutes.' }
}
Log 'Qwen ready.'

$candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\OpenGUI\OpenGUI.exe'),
    (Join-Path $env:LOCALAPPDATA 'OpenGUI\OpenGUI.exe'),
    (Join-Path $env:ProgramFiles 'OpenGUI\OpenGUI.exe')
)
if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} 'OpenGUI\OpenGUI.exe') }
$openGui = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $openGui) {
    foreach ($rp in @('HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\OpenGUI.exe','HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\OpenGUI.exe')) {
        try {
            $v = (Get-ItemProperty $rp -ErrorAction Stop).'(default)'
            if ($v -and (Test-Path -LiteralPath $v)) { $openGui = $v; break }
        } catch {}
    }
}
if (-not $openGui) { Fail 'OpenGUI.exe was not found.' }
$openGui = [System.IO.Path]::GetFullPath($openGui)
Set-Content -LiteralPath (Join-Path $runtime 'opengui_path.txt') -Value $openGui -Encoding UTF8

# ShellExecute launches the GUI independently from this hidden controller.
$shell = New-Object -ComObject Shell.Application
$shell.ShellExecute($openGui, '', $null, 'open', 1)
Log ('Opened OpenGUI: ' + $openGui)

# v15.28 lifecycle policy:
# OpenGUI no longer owns backend lifetime. Closing OpenGUI does not stop Qwen
# or media workers. The persistent Control Center notification-area icon owns
# explicit session shutdown through 'Stop PortableAI and Exit'.
Log 'Tray-owned lifecycle active; no OpenGUI-close shutdown watcher is armed.'
exit 0
