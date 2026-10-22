param([string]$PortalRoot)
if ([string]::IsNullOrWhiteSpace($PortalRoot)) { $PortalRoot = Split-Path -Parent $PSScriptRoot }
$PortalPython = Join-Path $PortalRoot 'Runtime\BootstrapPython\python.exe'
$PortalEndpointScript = Join-Path $PortalRoot 'Agent\instance_cli.py'
$PortalEndpointText = & $PortalPython -B -I $PortalEndpointScript status --root $PortalRoot
if ($LASTEXITCODE -ne 0) { throw 'Could not read this installation service endpoints.' }
$script:PortalServicePorts = ($PortalEndpointText | ConvertFrom-Json).active_ports
function Get-PortalPort([string]$Service) { return [int]$script:PortalServicePorts.$Service }
function Get-PortalServiceUrl([string]$Service, [string]$Suffix = '') {
    return ('http://127.0.0.1:' + (Get-PortalPort $Service) + $Suffix)
}
