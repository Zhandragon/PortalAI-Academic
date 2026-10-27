param(
    [Parameter(Mandatory=$true)][string]$Installer,
    [Parameter(Mandatory=$true)][string]$Sources,
    [Parameter(Mandatory=$true)][string]$RuntimeZip
)
# Run with Windows PowerShell (.NET Framework), matching the compiled installer.
$ErrorActionPreference='Stop'
$assembly=[Reflection.Assembly]::LoadFile([IO.Path]::GetFullPath($Installer))
$names=$assembly.GetManifestResourceNames()
$files=@{
    'python-bootstrap.zip'=$RuntimeZip
    'installer_core.py'=(Join-Path $Sources 'installer_core.py')
    'engine_cli.py'=(Join-Path $Sources 'engine_cli.py')
    'installer_storage.py'=(Join-Path $Sources 'installer_storage.py')
    'portable_update.py'=(Join-Path $Sources 'portable_update.py')
    'suite_installer.py'=(Join-Path $Sources 'suite_installer.py')
    'abliterator_installer_core.py'=(Join-Path $Sources 'abliterator_installer_core.py')
}
foreach ($name in $files.Keys) {
    if ($name -notin $names) { throw "Required embedded resource missing: $name" }
    $stream=$assembly.GetManifestResourceStream($name)
    $hasher=[Security.Cryptography.SHA256]::Create()
    try { $digest=[BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-','') }
    finally { $hasher.Dispose(); $stream.Dispose() }
    if ($digest -ne (Get-FileHash -LiteralPath $files[$name] -Algorithm SHA256).Hash) {
        throw "Embedded resource differs from the current source: $name"
    }
}
Write-Output 'All embedded suite resources match the source inventory.'
