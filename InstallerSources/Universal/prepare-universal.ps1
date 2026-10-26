param([switch]$VerifyOnly,[switch]$PrepareOnly)
$ErrorActionPreference = 'Stop'
$bundleRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$manifest = Get-Content -LiteralPath (Join-Path $bundleRoot 'universal.json') -Raw | ConvertFrom-Json
if ($manifest.schema -ne 1 -or @($manifest.assets).Count -ne 3) { throw 'Invalid universal package manifest.' }
if ((@($manifest.assets.platform | Sort-Object) -join ',') -ne 'Linux,Mac,Windows') { throw 'Each OS must appear exactly once.' }
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
    $downloadUrl = $asset.url
    if (-not $downloadUrl) {
        $releaseBase = Read-Host 'This release has not been assigned a Full-edition download URL. Enter its public GitHub release URL (https://github.com/OWNER/REPO/releases/download/TAG)'
        if ($releaseBase -notmatch '^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases/download/[A-Za-z0-9_.-]+$') { throw 'Invalid GitHub release URL.' }
        $downloadUrl = $releaseBase + '/' + $asset.file
    }
    $uri = [Uri]$downloadUrl
    if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'github.com' -or $uri.UserInfo) { throw 'Expected a public GitHub HTTPS release URL.' }
    $temporary = Assert-PlainPath ($path + '.part-' + [Guid]::NewGuid().ToString('N'))
    Write-Host "Downloading $($asset.platform): $([math]::Round($asset.bytes/1MB,1)) MiB"
    $client = [Net.WebClient]::new()
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    try {
        $client.DownloadFile($uri,$temporary)
        if (-not (Test-Asset $asset $temporary)) { throw 'Downloaded package failed its size/SHA-256 check.' }
        Move-Item -LiteralPath $temporary -Destination $path
    } finally {
        $client.Dispose()
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary }
    }
}
Write-Host 'All three OS packages are verified. Each OS completes its own native installation.'
if ($VerifyOnly -or $PrepareOnly) { return }
$answer = Read-Host 'Open the Windows installer now? [y/N]'
if ($answer -notmatch '^(?i:y|yes)$') { return }
$installerName = if ($manifest.edition -eq 'Academic') { 'PortalAI-Academic-Install.exe' } else { 'PortalAI-Install.exe' }
$windowsAsset = @($manifest.assets | Where-Object platform -eq 'Windows')[0]
$destination = Assert-PlainPath (Join-Path $bundleRoot ('Platforms\Windows-' + $manifest.version))
if (Test-Path -LiteralPath $destination) { throw 'An extracted installer already exists. Use its Windows installer, or choose a fresh universal folder.' }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::ExtractToDirectory((Join-Path $packages $windowsAsset.file),$destination)
Start-Process -FilePath (Join-Path $destination $installerName) -WorkingDirectory $destination
