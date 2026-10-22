param(
    [Parameter(Mandatory=$true)]
    [string]$Root,
    [string]$OpenGUIPath = ''
)

$ErrorActionPreference = 'SilentlyContinue'
$Root = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
$runtime = Join-Path $Root 'Agent\.runtime'
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$log = Join-Path $runtime 'portableai_lifecycle.log'

function Log([string]$Message) {
    try {
        Add-Content -LiteralPath $log -Value (
            (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $Message
        ) -Encoding UTF8
    } catch {}
}

# Compatibility shim only. Older launchers may still invoke this file.
# Auto-shutdown-on-OpenGUI-close is disabled in v15.28.
Log 'Lifecycle watcher v15.28 invoked. Auto-shutdown-on-OpenGUI-close is disabled; exiting harmlessly.'
exit 0
