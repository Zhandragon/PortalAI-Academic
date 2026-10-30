param(
    [string]$Root = '',
    [switch]$SkipCustomVoice,
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
# Compatibility entry point: do not recreate the retired private Python tree.
$Repair = Join-Path $PSScriptRoot '..\Qwen3-TTS\Install_or_Repair_Qwen3_TTS.ps1'
$Arguments = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Repair, '-Root', $Root)
if ($SkipCustomVoice) { $Arguments += '-SkipCustomVoice' }
if ($VerifyOnly) { $Arguments += '-VerifyOnly' }
& powershell.exe @Arguments
exit $LASTEXITCODE
