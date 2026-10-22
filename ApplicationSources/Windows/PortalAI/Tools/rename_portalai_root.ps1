# A same-parent rename only. Never recursively move/copy a live installed bundle.
# PowerShell 7 callers can pass a PSModulePath that omits Windows PowerShell's
# built-in modules. Repair only this process's search path, never host settings.
param([Parameter(Mandatory=$true)][string]$DriveRoot)
if($PSVersionTable.PSEdition -eq 'Desktop') {
    $env:PSModulePath=(Join-Path $PSHOME 'Modules')+';'+$env:PSModulePath
}
function Invoke-PortalAIRootRename {
    param([Parameter(Mandatory=$true)][string]$DriveRoot)
    $ErrorActionPreference='Stop'
    $base=[IO.Path]::GetFullPath($DriveRoot)
    $modern=[IO.Path]::GetFullPath((Join-Path $base 'PortalAI'))
    $legacy=[IO.Path]::GetFullPath((Join-Path $base 'PortableAI'))
    $source=$null
    if(Test-Path -LiteralPath $modern){$source=$modern}
    if(Test-Path -LiteralPath $legacy){if($null -ne $source){throw 'Both legacy root names exist; refusing an ambiguous migration'};$source=$legacy}
    $target=[IO.Path]::GetFullPath((Join-Path $base 'PortalAI Windows'))
    if((Split-Path -Parent $target).TrimEnd('\') -ne $base.TrimEnd('\') -or ($null -ne $source -and (Split-Path -Parent $source).TrimEnd('\') -ne $base.TrimEnd('\'))) { throw 'Unexpected rename scope' }
    if(Test-Path -LiteralPath $target) {
        if(($null -ne $source) -or -not(Test-Path -LiteralPath (Join-Path $target 'Runtime\BootstrapPython\python.exe'))) { throw 'Destination exists; refusing replacement or ambiguous installations' }
        return @{renamed=$true;already_renamed=$true;root=$target}
    }
    if($null -eq $source){throw 'No PortalAI or PortableAI source folder was found'}
    $directory=Get-Item -LiteralPath $source
    if(-not $directory.PSIsContainer -or ($directory.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Linked or invalid bundle root' }
    $checks=@('PortalAI.exe','PortalAI.sh','Runtime\BootstrapPython\python.exe','ControlCenter\control_center_bootstrap.py','Agent\profile_paths.py','Agent\hardware_profiles.json')
    $before=@{}
    foreach($relative in $checks) { $before[$relative]=(Get-FileHash -LiteralPath (Join-Path $source $relative) -Algorithm SHA256).Hash }
    $private=Join-Path $source 'Private'
    function Assert-PlainPath([string]$path) {
        $item=Get-Item -LiteralPath $path -Force
        if($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked account paths are refused' }
    }
    $lock=$null
    try {
        if(Test-Path -LiteralPath $private) {
            Assert-PlainPath $private
            Assert-PlainPath (Join-Path $private 'Users')
            $lockPath=Join-Path $private 'profile-runtime.lock'
            Assert-PlainPath $lockPath
            $lock=[IO.File]::Open($lockPath,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
            $lock.Lock(0,1)
            $markerPath=Join-Path $private 'active-session.json'
            Assert-PlainPath $markerPath
            if((Get-Item -LiteralPath $markerPath).Length -gt 16384) { throw 'Invalid account state' }
            $marker=Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json
            if($marker.state -ne 'closed') { throw 'Exit PortalAI normally and wait for account sealing before renaming' }
            foreach($profile in Get-ChildItem -LiteralPath (Join-Path $private 'Users') -Directory -Force) {
                Assert-PlainPath $profile.FullName
                $workspace=Join-Path $profile.FullName 'Workspace'
                if(Test-Path -LiteralPath $workspace) {
                    Assert-PlainPath $workspace
                    if(Get-ChildItem -LiteralPath $workspace -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | Select-Object -First 1) { throw 'Linked private workspace refused' }
                    if(Get-ChildItem -LiteralPath $workspace -File -Recurse -Force | Select-Object -First 1) { throw 'A private workspace is not empty; authenticated recovery is required first' }
                }
            }
        }
        $running=@(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like ($source+'\*') })
        if($running.Count) { throw 'A bundled application is still running; close it normally first' }
        # Windows also prevents renaming a directory around our own open lock
        # file. Release only this verifier's handle immediately before rename.
        # A competing normal launcher/runtime will hold its own bundle files;
        # Windows then refuses the metadata rename without moving any children.
        if($null -ne $lock) { $lock.Unlock(0,1);$lock.Dispose();$lock=$null }
        # Rename-Item performs a same-parent metadata rename. Move-Item can fall
        # back to recursive moves on Windows and must NOT be substituted here.
        Rename-Item -LiteralPath $source -NewName 'PortalAI Windows' -ErrorAction Stop
        foreach($relative in $checks) {
            if((Get-FileHash -LiteralPath (Join-Path $target $relative) -Algorithm SHA256).Hash -ne $before[$relative]) { throw ('Post-rename checksum mismatch: '+$relative) }
        }
        $receipt=@{renamed=$true;source=$source;root=$target;checksums_verified=$true;checked_sha256=$before;time=(Get-Date).ToString('o')}
        $receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $target 'Maintenance\Patches\root-relocation-20261017.json') -Encoding utf8
        return $receipt
    } finally {
        if($null -ne $lock) { try { $lock.Unlock(0,1) } finally { $lock.Dispose() } }
    }
}

Invoke-PortalAIRootRename -DriveRoot $DriveRoot
