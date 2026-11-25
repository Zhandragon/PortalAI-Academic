param([switch]$VerifyOnly,[switch]$PrepareOnly,[switch]$ExtractOnly)
$ErrorActionPreference = 'Stop'
$bundleRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$manifest = Get-Content -LiteralPath (Join-Path $bundleRoot 'bundle.json') -Raw | ConvertFrom-Json
if ($manifest.schema -ne 1 -or @($manifest.assets).Count -notin @(1,3)) { throw 'Invalid universal package manifest.' }
if (@($manifest.assets.platform | Select-Object -Unique).Count -ne @($manifest.assets).Count) { throw 'Duplicate platform.' }
function Assert-PlainPath([string]$Path) {
    $resolved = [IO.Path]::GetFullPath($Path)
    if (-not $resolved.StartsWith($bundleRoot + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Path escapes the universal folder.' }
    $probe = $resolved
    while ($probe) {
        if (Test-Path -LiteralPath $probe) {
            if ((Get-Item -LiteralPath $probe -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked path refused: $probe" }
        }
        $probe = [IO.Path]::GetDirectoryName($probe)
    }
    return $resolved
}
function Test-Asset($Asset,[string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf) -or (Get-Item -LiteralPath $Path).Length -ne $Asset.bytes) { return $false }
    $stream = [IO.File]::OpenRead($Path)
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { $digest = [BitConverter]::ToString($hasher.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $hasher.Dispose(); $stream.Dispose() }
    return $digest -eq $Asset.sha256
}
$packages = Assert-PlainPath (Join-Path $bundleRoot 'Packages')
if (-not $VerifyOnly) { New-Item -ItemType Directory -Path $packages -Force | Out-Null }
$driveInfo = [IO.DriveInfo]::new([IO.Path]::GetPathRoot($bundleRoot))
$needed = 512MB
foreach ($asset in $manifest.assets) {
    if ($asset.platform -notin @('Windows','Linux','Mac') -or $asset.file -notmatch '^[A-Za-z0-9._-]+$' -or $asset.sha256 -notmatch '^[a-f0-9]{64}$' -or $asset.bytes -le 0) { throw 'Invalid asset pin.' }
    $path = Assert-PlainPath (Join-Path $packages $asset.file)
    if (-not (Test-Asset $asset $path)) { $needed += [long]$asset.bytes }
}
if (-not $VerifyOnly -and $driveInfo.AvailableFreeSpace -lt $needed) { throw 'Insufficient free space to prepare all three OS packages. Nothing downloaded.' }
foreach ($asset in $manifest.assets) {
    $path = Assert-PlainPath (Join-Path $packages $asset.file)
    if (Test-Asset $asset $path) { Write-Host "Verified $($asset.platform) package"; continue }
    if ($VerifyOnly) { throw "Missing or corrupt $($asset.platform) package." }
    if (Test-Path -LiteralPath $path) { throw "Existing package differs from its release pin; review it before retrying: $path" }
    throw 'An included installer is missing or corrupt. Extract a fresh copy of the complete bundle; see START_HERE.txt.'
}
Write-Host 'All included OS packages are verified. Each OS completes its own native installation.'
$updatedLauncher = $null
if ($manifest.windows_launcher) {
    $launcher = $manifest.windows_launcher
    if ($launcher.file -ne 'Setup/PortalAI-Setup.exe' -or $launcher.sha256 -notmatch '^[a-f0-9]{64}$' -or $launcher.bytes -le 0) { throw 'Invalid Windows setup launcher pin.' }
    $updatedLauncher = Assert-PlainPath (Join-Path $bundleRoot $launcher.file)
    if (-not (Test-Asset $launcher $updatedLauncher)) { throw 'The updated Windows setup launcher is missing or corrupt. Extract a fresh complete bundle.' }
} elseif ($manifest.version -in @('2026.11.25-bundle3','2026.11.25-bundle4','2026.11.25-bundle5','2026.11.25-bundle6') -and 'Windows' -in @($manifest.assets.platform)) {
    throw 'The Windows setup launcher pin is missing.'
}
if ($manifest.version -in @('2026.11.25-bundle4','2026.11.25-bundle5','2026.11.25-bundle6') -and -not $manifest.model_catalog_version) { throw 'The complete model catalog is missing.' }
foreach ($file in $manifest.setup_files) {
    if ($file.file -notmatch '^Setup/[A-Za-z0-9._/-]+$' -or $file.file -match '(^|/)\.\.(/|$)' -or $file.sha256 -notmatch '^[a-f0-9]{64}$' -or $file.bytes -le 0) { throw 'Invalid model setup file pin.' }
    if (-not (Test-Asset $file (Assert-PlainPath (Join-Path $bundleRoot $file.file)))) { throw "Missing or corrupt model setup file: $($file.file)" }
}
if ($manifest.model_catalog_version) {
    $localPath = Join-Path $bundleRoot 'Setup/Windows/suite-local.json'
    if ('Windows' -in @($manifest.assets.platform)) {
        $local = Get-Content -LiteralPath $localPath -Raw | ConvertFrom-Json
        foreach ($asset in $local.assets) { foreach ($pin in $asset.files) {
            if (-not $pin.source_file.StartsWith('Utilities/Windows/') -or -not $pin.file.StartsWith('SuiteAssets/')) { throw 'Invalid bundled companion location.' }
            if (-not (Test-Asset $pin (Assert-PlainPath (Join-Path $bundleRoot $pin.source_file)))) { throw "Bundled companion failed verification: $($pin.source_file)" }
        } }
    }
}
if ($VerifyOnly -or $PrepareOnly) { return }
if ('Windows' -notin @($manifest.assets.platform)) { throw 'This bundle does not include Windows. Use the matching OS bundle or Universal.' }
if (-not $ExtractOnly) {
    $answer = Read-Host 'Open the Windows installer now? [y/N]'
    if ($answer -notmatch '^(?i:y|yes)$') { return }
}
$installerName = $manifest.windows_installer
if ($installerName -notin @('PortalAI-Install.exe','PortalAI-Academic-Install.exe')) { throw 'Unexpected Windows installer entry point.' }
$windowsAsset = @($manifest.assets | Where-Object platform -eq 'Windows')[0]
$destination = Assert-PlainPath (Join-Path $bundleRoot ('Platforms\Windows-' + $manifest.version))
if (Test-Path -LiteralPath $destination) { throw 'An extracted installer already exists. Use its Windows installer, or choose a fresh universal folder.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $packages $windowsAsset.file),$destination)
if ($updatedLauncher) { Copy-Item -LiteralPath $updatedLauncher -Destination (Join-Path $destination $installerName) -Force }
foreach ($file in $manifest.setup_files) {
    if ($file.file.StartsWith('Setup/Windows/')) {
        $relative = $file.file.Substring('Setup/Windows/'.Length)
        $target = Assert-PlainPath (Join-Path $destination $relative)
        New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($target)) -Force | Out-Null
        Copy-Item -LiteralPath (Join-Path $bundleRoot $file.file) -Destination $target
    }
}
if ($local) { foreach ($asset in $local.assets) { foreach ($pin in $asset.files) {
    $target = Assert-PlainPath (Join-Path $destination $pin.file)
    if (-not $target.StartsWith($destination + [IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) { throw 'Companion path escapes the prepared installer.' }
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($target)) -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $bundleRoot $pin.source_file) -Destination $target
} } }
if ($manifest.model_catalog_version) {
    $packagePinPath = Join-Path $destination 'PACKAGE_SHA256.json'
    $pins = [Collections.Generic.List[object]]::new()
    foreach ($pin in (Get-Content -LiteralPath $packagePinPath -Raw | ConvertFrom-Json)) {
        if ($pin.path -eq $installerName) { $pins.Add([pscustomobject]@{path=$installerName;bytes=$launcher.bytes;sha256=$launcher.sha256}) }
        else { $pins.Add($pin) }
    }
    foreach ($file in $manifest.setup_files) {
        if ($file.file.StartsWith('Setup/Windows/')) {
            $relative = $file.file.Substring('Setup/Windows/'.Length)
            foreach ($existingPin in @($pins | Where-Object { $_.path -eq $relative })) { $pins.Remove($existingPin) | Out-Null }
            $pins.Add([pscustomobject]@{path=$relative;bytes=$file.bytes;sha256=$file.sha256})
        }
    }
    foreach ($asset in $local.assets) { foreach ($pin in $asset.files) { $pins.Add([pscustomobject]@{path=$pin.file;bytes=$pin.bytes;sha256=$pin.sha256}) } }
    [IO.File]::WriteAllText($packagePinPath,($pins | ConvertTo-Json -Depth 10),[Text.UTF8Encoding]::new($false))
}
if ($ExtractOnly) { Write-Host "Prepared $destination"; return }
Start-Process -FilePath (Join-Path $destination $installerName) -WorkingDirectory $destination -ArgumentList ('--destination=' + [IO.Path]::GetPathRoot($bundleRoot))
