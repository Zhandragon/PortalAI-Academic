param([Parameter(Mandatory=$true)][string]$Root, [switch]$IncludeOpenGUI, [switch]$Quiet)
$ErrorActionPreference = 'Stop'
# Legacy entry point uses the current identity-verified shutdown. Never kill by
# global process name or by port. Close the GUI through its normal sealed Exit.
$Python = Join-Path $Root 'Runtime\BootstrapPython\python.exe'
$StopScript = Join-Path $Root 'Launchers\Stop_PortableAI.py'
$Arguments = @('-B','-I',$StopScript,'--root',$Root)
if ($Quiet) { $Arguments += '--quiet' }
& $Python @Arguments
exit $LASTEXITCODE
