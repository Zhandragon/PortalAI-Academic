param(
    [Parameter(Mandatory=$true)]
    [string]$Root
)

$ErrorActionPreference = "Stop"
$Root = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
$runtime = Join-Path $Root "Agent\.runtime"
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

$candidates = @(
    (Join-Path $env:LOCALAPPDATA 'Programs\OpenGUI\OpenGUI.exe'),
    (Join-Path $env:LOCALAPPDATA 'OpenGUI\OpenGUI.exe'),
    (Join-Path $env:ProgramFiles 'OpenGUI\OpenGUI.exe')
)
if (${env:ProgramFiles(x86)}) {
    $candidates += (Join-Path ${env:ProgramFiles(x86)} 'OpenGUI\OpenGUI.exe')
}

$exe = $candidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $exe) {
    foreach ($rp in @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\App Paths\OpenGUI.exe',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\App Paths\OpenGUI.exe'
    )) {
        try {
            $v = (Get-ItemProperty $rp -ErrorAction Stop).'(default)'
            if ($v -and (Test-Path -LiteralPath $v)) { $exe = $v; break }
        } catch {}
    }
}
if (-not $exe) {
    $cmd = Get-Command OpenGUI.exe -ErrorAction SilentlyContinue
    if ($cmd) { $exe = $cmd.Source }
}
if (-not $exe) { exit 2 }

$exe = [System.IO.Path]::GetFullPath($exe)
Set-Content -LiteralPath (Join-Path $runtime 'opengui_path.txt') -Value $exe -Encoding UTF8

# ShellExecute keeps OpenGUI detached from the launcher console.
$shell = New-Object -ComObject Shell.Application
$shell.ShellExecute($exe, '', $null, 'open', 1)

# Start a hidden watcher that shuts down PortableAI backends once this OpenGUI
# installation is no longer running.
$watcher = Join-Path $Root 'Launchers\PortableAI_Lifecycle_Watcher.ps1'
if (Test-Path -LiteralPath $watcher) {
    Start-Process `
        -FilePath 'powershell.exe' `
        -ArgumentList @(
            '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-WindowStyle','Hidden',
            '-File', ('"{0}"' -f $watcher),
            '-Root', ('"{0}"' -f $Root),
            '-OpenGUIPath', ('"{0}"' -f $exe)
        ) `
        -WindowStyle Hidden
}

Write-Host ('[OK] OpenGUI detached and lifecycle watcher armed: ' + $exe)
exit 0
