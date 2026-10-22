param(
    [Parameter(Mandatory=$true)]
    [string]$Root,
    [Parameter(Mandatory=$true)]
    [int]$GpuLayers,
    [Parameter(Mandatory=$true)]
    [int]$IdleSleep,
    [int]$Context = 32768
)
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'Launchers\InstancePorts.ps1') -PortalRoot $Root


$ErrorActionPreference = "Stop"

$llama   = Join-Path $Root "LLM\llamacpp\llama-server.exe"
$model   = Join-Path $Root "LLM\models\Qwen3.8-27B-Q4_K_M.gguf"
$mmproj  = Join-Path $Root "LLM\models\mmproj-Qwen3.8-27B-Standard-BF16.gguf"
$runtime = Join-Path $Root "Agent\.runtime"

New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$stdout = Join-Path $runtime "qwen_server.log"
$stderr = Join-Path $runtime "qwen_server_error.log"
$pidFile = Join-Path $runtime "qwen_pid.txt"
$helperPidFile = Join-Path $runtime "qwen_helper_pid.txt"

$arguments = @(
    ('-m "{0}"' -f $model)
    ('--mmproj "{0}"' -f $mmproj)
    '--no-mmproj-offload'
    ('-ngl {0}' -f $GpuLayers)
    ('-c {0}' -f $Context)
    ('--sleep-idle-seconds {0}' -f $IdleSleep)
    '--metrics'
    '--host 127.0.0.1'
    ('--port ' + (Get-PortalPort 'qwen'))
) -join ' '

# A hidden helper owns Qwen's redirected stdout/stderr and exits when Qwen exits.
$helper = @"
`$ErrorActionPreference = 'Stop'
`$root = '$($Root.Replace("'","''"))'
`$runtime = '$($runtime.Replace("'","''"))'
`$pidFile = '$($pidFile.Replace("'","''"))'
`$helperPidFile = '$($helperPidFile.Replace("'","''"))'
Set-Content -LiteralPath `$helperPidFile -Value `$PID -Encoding ASCII

`$psi = New-Object System.Diagnostics.ProcessStartInfo
`$psi.FileName = '$($llama.Replace("'","''"))'
`$psi.Arguments = '$($arguments.Replace("'","''"))'
`$psi.WorkingDirectory = `$root
`$psi.UseShellExecute = `$false
`$psi.CreateNoWindow = `$true
`$psi.RedirectStandardOutput = `$true
`$psi.RedirectStandardError = `$true

`$proc = New-Object System.Diagnostics.Process
`$proc.StartInfo = `$psi

`$outPath = '$($stdout.Replace("'","''"))'
`$errPath = '$($stderr.Replace("'","''"))'
`$utf8 = New-Object System.Text.UTF8Encoding(`$false)
`$outWriter = New-Object System.IO.StreamWriter(`$outPath, `$false, `$utf8)
`$errWriter = New-Object System.IO.StreamWriter(`$errPath, `$false, `$utf8)
`$outWriter.AutoFlush = `$true
`$errWriter.AutoFlush = `$true

`$proc.add_OutputDataReceived({ param(`$s,`$e) if (`$null -ne `$e.Data) { `$outWriter.WriteLine(`$e.Data) } })
`$proc.add_ErrorDataReceived({ param(`$s,`$e) if (`$null -ne `$e.Data) { `$errWriter.WriteLine(`$e.Data) } })

try {
    if (-not `$proc.Start()) { throw 'Failed to start llama-server.exe' }
    Set-Content -LiteralPath `$pidFile -Value `$proc.Id -Encoding ASCII
    `$proc.BeginOutputReadLine()
    `$proc.BeginErrorReadLine()
    `$proc.WaitForExit()
    exit `$proc.ExitCode
}
finally {
    try { `$outWriter.Dispose() } catch {}
    try { `$errWriter.Dispose() } catch {}
    Remove-Item -LiteralPath `$pidFile -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath `$helperPidFile -Force -ErrorAction SilentlyContinue
}
"@

$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($helper))

Start-Process `
    -FilePath "powershell.exe" `
    -ArgumentList "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand $encoded" `
    -WindowStyle Hidden

exit 0
