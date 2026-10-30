# PORTABLEAI_SCIENCE_CAPABILITY_SYNC_v15_130
param(
    [Parameter(Mandatory=$true)]
    [string]$Root,
    [Parameter(Mandatory=$true)]
    [int]$OwnerPid
)
. (Join-Path (Split-Path -Parent $PSScriptRoot) 'Launchers\InstancePorts.ps1') -PortalRoot $Root


$ErrorActionPreference = 'SilentlyContinue'
$Root = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')
$Runtime = Join-Path $Root 'Agent\.runtime'
New-Item -ItemType Directory -Force -Path $Runtime | Out-Null

$StatusPath = Join-Path $Runtime 'control_center_status.json'
$TempPath = Join-Path $Runtime 'control_center_status.tmp'
$ForcePath = Join-Path $Runtime 'control_center_force_scan.flag'
$GpuStatePath = Join-Path $Runtime 'gpu_model_state.json'
$WorkerLog = Join-Path $Runtime 'control_center_status_worker.log'

$PollSeconds = 3
$GpuPollSeconds = 10
$PropsPollSeconds = 15
$InventoryPollSeconds = 300

$LastGpuPoll = [DateTime]::MinValue
$LastPropsPoll = [DateTime]::MinValue
$LastInventoryPoll = [DateTime]::MinValue

$CachedGpu = @{ summary='GPU telemetry pending'; utilization=0.0; models=@() }
$CachedQwenProps = $null
$InstalledCache = $null

$ActivityMemory = @{
    qwen  = @{ busy_since=$null; last_change=(Get-Date); fingerprint='' }
    comfy = @{ busy_since=$null; last_change=(Get-Date); fingerprint='' }
    ace   = @{ busy_since=$null; last_change=(Get-Date); fingerprint='' }
}

function Log([string]$Message) {
    try {
        Add-Content -LiteralPath $WorkerLog `
            -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $Message) `
            -Encoding UTF8
    } catch {}
}

function Owner-Alive {
    try { return $null -ne (Get-Process -Id $OwnerPid -ErrorAction SilentlyContinue) }
    catch { return $false }
}

function Test-Tcp([int]$Port, [int]$TimeoutMs = 150) {
    try {
        $c = New-Object System.Net.Sockets.TcpClient
        $ar = $c.BeginConnect('127.0.0.1', $Port, $null, $null)
        $ok = $ar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)
        if (-not $ok) { $c.Close(); return $false }
        $c.EndConnect($ar)
        $c.Close()
        return $true
    } catch { return $false }
}

function Get-Json([string]$Url, [int]$TimeoutSec = 1) {
    try { return Invoke-RestMethod -Uri $Url -Method Get -TimeoutSec $TimeoutSec }
    catch { return $null }
}

function Get-Text([string]$Url, [int]$TimeoutSec = 1) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        if ([int]$r.StatusCode -ge 200 -and [int]$r.StatusCode -lt 400) {
            return [string]$r.Content
        }
    } catch {}
    return $null
}

function Test-Http([string]$Url, [int]$TimeoutSec = 1) {
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return ([int]$r.StatusCode -ge 200 -and [int]$r.StatusCode -lt 500)
    } catch { return $false }
}

function Run-HiddenCapture([string]$FileName, [string]$Arguments, [int]$TimeoutMs = 1600) {
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $FileName
        $psi.Arguments = $Arguments
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $p = [System.Diagnostics.Process]::Start($psi)
        if (-not $p.WaitForExit($TimeoutMs)) {
            try { $p.Kill() } catch {}
            return ''
        }
        return $p.StandardOutput.ReadToEnd()
    } catch { return '' }
}

function File-Exists([string]$Relative) {
    Test-Path -LiteralPath (Join-Path $Root $Relative)
}

function Files-Exist([string[]]$Relatives) {
    foreach ($r in $Relatives) {
        if (-not (File-Exists $r)) { return $false }
    }
    return $true
}

function File-Contains([string]$Relative, [string]$Needle) {
    $path = Join-Path $Root $Relative
    if (-not (Test-Path -LiteralPath $path)) { return $false }
    try {
        return $null -ne (
            Select-String -LiteralPath $path -SimpleMatch $Needle -Quiet -ErrorAction SilentlyContinue
        )
    } catch {
        return $false
    }
}

function Inventory([string]$RelativeDir, [string[]]$Patterns) {
    $dir = Join-Path $Root $RelativeDir
    if (-not (Test-Path -LiteralPath $dir)) { return @() }

    $items = @()
    foreach ($pat in $Patterns) {
        # Model folders here are flat in PortableAI. Avoid recursive scans.
        $items += @(Get-ChildItem -LiteralPath $dir -Filter $pat -File -ErrorAction SilentlyContinue)
    }
    @($items | Sort-Object Name -Unique | ForEach-Object { $_.Name })
}

function Get-PromMetric([string]$Text, [string]$Metric) {
    if ([string]::IsNullOrWhiteSpace($Text)) { return $null }
    $escaped = [Regex]::Escape($Metric)
    $m = [Regex]::Match($Text, "(?m)^" + $escaped + "(?:\{[^\r\n]*\})?\s+([-+0-9.eE]+)\s*$")
    if (-not $m.Success) { return $null }
    $v = 0.0
    if ([double]::TryParse(
        $m.Groups[1].Value,
        [Globalization.NumberStyles]::Float,
        [Globalization.CultureInfo]::InvariantCulture,
        [ref]$v
    )) { return $v }
    return $null
}

function Format-Elapsed([DateTime]$Since) {
    if ($null -eq $Since) { return '' }
    $span = (Get-Date) - $Since
    if ($span.TotalHours -ge 1) {
        return ('{0}h {1}m' -f [int]$span.TotalHours, $span.Minutes)
    }
    if ($span.TotalMinutes -ge 1) {
        return ('{0}m {1}s' -f [int]$span.TotalMinutes, $span.Seconds)
    }
    return ('{0}s' -f [int]$span.TotalSeconds)
}

function Update-BusyMemory(
    [string]$Key,
    [bool]$Busy,
    [string]$Fingerprint
) {
    $mem = $ActivityMemory[$Key]
    $now = Get-Date

    if (-not $Busy) {
        $mem.busy_since = $null
        $mem.last_change = $now
        $mem.fingerprint = $Fingerprint
        return $mem
    }

    if ($null -eq $mem.busy_since) {
        $mem.busy_since = $now
        $mem.last_change = $now
        $mem.fingerprint = $Fingerprint
        return $mem
    }

    if ($mem.fingerprint -ne $Fingerprint) {
        $mem.fingerprint = $Fingerprint
        $mem.last_change = $now
    }

    return $mem
}

function Get-GpuState {
    $summary = $CachedGpu.summary
    $util = [double]$CachedGpu.utilization

    if (((Get-Date) - $LastGpuPoll).TotalSeconds -ge $GpuPollSeconds) {
        $out = Run-HiddenCapture 'nvidia-smi.exe' `
            '--query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits' 1600

        if (-not [string]::IsNullOrWhiteSpace($out)) {
            $line = ($out -split "`r?`n" | Where-Object { $_.Trim() } | Select-Object -First 1)
            $parts = $line -split ','
            if ($parts.Count -ge 4) {
                $used = 0.0
                $total = 0.0
                $parsedUtil = 0.0
                [double]::TryParse($parts[1].Trim(), [ref]$used) | Out-Null
                [double]::TryParse($parts[2].Trim(), [ref]$total) | Out-Null
                [double]::TryParse($parts[3].Trim(), [ref]$parsedUtil) | Out-Null
                $util = $parsedUtil
                $summary = ('{0} - {1:N1}/{2:N1} GB VRAM - {3}% GPU' -f `
                    $parts[0].Trim(), ($used/1024), ($total/1024), [int]$parsedUtil)
            }
        }

        $script:LastGpuPoll = Get-Date
        $CachedGpu.summary = $summary
        $CachedGpu.utilization = $util
    }

    $models = New-Object System.Collections.Generic.List[string]

    if ($CachedQwenProps) {
        $sleeping = $false
        try { $sleeping = [bool]$CachedQwenProps.is_sleeping } catch {}
        if (-not $sleeping) {
            $mp = ''
            try { $mp = [string]$CachedQwenProps.model_path } catch {}
            if (-not [string]::IsNullOrWhiteSpace($mp)) {
                $models.Add(('Qwen - ' + [System.IO.Path]::GetFileName($mp)))
            } elseif (Test-Tcp (Get-PortalPort 'qwen')) {
                $models.Add('Qwen - llama.cpp model awake')
            }
        }
    }

    if (Test-Path -LiteralPath $GpuStatePath) {
        try {
            $state = Get-Content -LiteralPath $GpuStatePath -Raw | ConvertFrom-Json
            $service = [string]$state.service
            $valid = $true

            if ($service -eq 'comfyui' -and -not (Test-Tcp (Get-PortalPort 'comfyui'))) { $valid = $false }
            if ($service -eq 'acestep' -and -not (Test-Tcp (Get-PortalPort 'acestep'))) { $valid = $false }

            if ($service -eq 'qwen3-tts') {
                $age = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [double]$state.updated_at
                if ($age -gt 7200) { $valid = $false }
            }

            if ($valid) {
                foreach ($m in @($state.models)) {
                    if (-not [string]::IsNullOrWhiteSpace([string]$m)) {
                        $label = switch ($service) {
                            'comfyui' { 'ComfyUI' }
                            'acestep' { 'ACE-Step' }
                            'qwen3-tts' { 'Qwen3-TTS' }
                            default { $service }
                        }
                        $models.Add(('{0} - {1}' -f $label, [string]$m))
                    }
                }
            }
        } catch {}
    }

    @{
        summary=$summary
        utilization=$util
        models=@($models)
    }
}

function Get-QwenState {
    $port = Test-Tcp (Get-PortalPort 'qwen')
    if (-not $port) {
        Update-BusyMemory 'qwen' $false 'offline' | Out-Null
        return @{
            server=@{ state='STOPPED'; detail='llama.cpp; :8080' }
            activity=@{ state='OFFLINE'; detail='server is not running' }
        }
    }

    if (((Get-Date) - $LastPropsPoll).TotalSeconds -ge $PropsPollSeconds -or $null -eq $CachedQwenProps) {
        $script:CachedQwenProps = Get-Json (Get-PortalServiceUrl 'qwen' '/props') 1
        $script:LastPropsPoll = Get-Date
    }

    $sleeping = $false
    try { $sleeping = [bool]$CachedQwenProps.is_sleeping } catch {}

    if ($sleeping) {
        Update-BusyMemory 'qwen' $false 'sleeping' | Out-Null
        return @{
            server=@{ state='SLEEPING'; detail='server alive; model unloaded; :8080' }
            activity=@{ state='SLEEPING'; detail='idle-sleep active; monitoring does not wake it' }
        }
    }

    $health = Test-Http (Get-PortalServiceUrl 'qwen' '/health') 1
    if (-not $health) {
        return @{
            server=@{ state='STARTING'; detail='server alive; model loading; :8080' }
            activity=@{ state='STARTING'; detail='waiting for model load' }
        }
    }

    $detail = 'llama.cpp; :8080'
    try {
        if ($CachedQwenProps.model_path) {
            $detail = ([System.IO.Path]::GetFileName([string]$CachedQwenProps.model_path) + '; :8080')
        }
    } catch {}

    # /metrics is deliberately used rather than /slots:
    # llama.cpp documents /metrics as exempt from idle-sleep wake/reset.
    $metrics = Get-Text (Get-PortalServiceUrl 'qwen' '/metrics') 1
    if ([string]::IsNullOrWhiteSpace($metrics)) {
        Update-BusyMemory 'qwen' $false 'metrics-unavailable' | Out-Null
        return @{
            server=@{ state='READY'; detail=$detail }
            activity=@{
                state='MONITORING UNAVAILABLE'
                detail='restart Qwen after v15.8 to enable lightweight --metrics'
            }
        }
    }

    $processing = Get-PromMetric $metrics 'llamacpp:requests_processing'
    $deferred = Get-PromMetric $metrics 'llamacpp:requests_deferred'
    $promptTokens = Get-PromMetric $metrics 'llamacpp:prompt_tokens_total'
    $predTokens = Get-PromMetric $metrics 'llamacpp:tokens_predicted_total'
    $tokSec = Get-PromMetric $metrics 'llamacpp:predicted_tokens_seconds'

    if ($null -eq $processing) { $processing = 0.0 }
    if ($null -eq $deferred) { $deferred = 0.0 }
    if ($null -eq $promptTokens) { $promptTokens = 0.0 }
    if ($null -eq $predTokens) { $predTokens = 0.0 }

    $busy = ($processing -gt 0 -or $deferred -gt 0)
    $fingerprint = ('{0}|{1}|{2}|{3}' -f $processing,$deferred,$promptTokens,$predTokens)
    $mem = Update-BusyMemory 'qwen' $busy $fingerprint

    if (-not $busy) {
        return @{
            server=@{ state='READY'; detail=$detail }
            activity=@{ state='IDLE'; detail='no inference request active' }
        }
    }

    $unchanged = ((Get-Date) - $mem.last_change).TotalSeconds
    if ($processing -gt 0 -and $unchanged -ge 90) {
        return @{
            server=@{ state='READY'; detail=$detail }
            activity=@{
                state='POSSIBLY STALLED'
                detail=('busy {0}; token counters unchanged for {1}s' -f `
                    (Format-Elapsed $mem.busy_since), [int]$unchanged)
            }
        }
    }

    if ($processing -gt 0) {
        $speed = ''
        if ($null -ne $tokSec -and $tokSec -gt 0) {
            $speed = ('; {0:N1} tok/s' -f $tokSec)
        }
        return @{
            server=@{ state='READY'; detail=$detail }
            activity=@{
                state='PROCESSING'
                detail=('active inference for {0}{1}; deferred={2}' -f `
                    (Format-Elapsed $mem.busy_since), $speed, [int]$deferred)
            }
        }
    }

    return @{
        server=@{ state='READY'; detail=$detail }
        activity=@{
            state='QUEUED'
            detail=('{0} request(s) deferred' -f [int]$deferred)
        }
    }
}

function Get-ComfyState([double]$GpuUtil) {
    if (-not (Test-Tcp (Get-PortalPort 'comfyui'))) {
        Update-BusyMemory 'comfy' $false 'offline' | Out-Null
        return @{
            server=@{ state='STOPPED'; detail='on-demand; :8188' }
            activity=@{ state='OFFLINE'; detail='starts automatically when a media task needs it' }
        }
    }

    $health = Test-Http (Get-PortalServiceUrl 'comfyui' '/system_stats') 1
    if (-not $health) {
        $mem = $ActivityMemory.comfy
        $state = if ($null -ne $mem.busy_since -and ((Get-Date)-$mem.busy_since).TotalSeconds -gt 30) {
            'POSSIBLY STALLED'
        } else { 'STARTING' }

        return @{
            server=@{ state='PORT OPEN'; detail='ComfyUI port open; API unavailable' }
            activity=@{ state=$state; detail='status API is not responding' }
        }
    }

    # /prompt is intentionally used instead of /queue. It returns only
    # exec_info.queue_remaining and avoids downloading the full workflow graph.
    $promptInfo = Get-Json (Get-PortalServiceUrl 'comfyui' '/prompt') 1
    $remaining = 0
    try { $remaining = [int]$promptInfo.exec_info.queue_remaining } catch {}

    $busy = ($remaining -gt 0)
    $fingerprint = [string]$remaining
    $mem = Update-BusyMemory 'comfy' $busy $fingerprint

    if (-not $busy) {
        return @{
            server=@{ state='READY'; detail='ComfyUI API; :8188' }
            activity=@{ state='IDLE'; detail='queue_remaining=0' }
        }
    }

    $busySeconds = ((Get-Date) - $mem.busy_since).TotalSeconds
    # Conservative stall flag: very long job AND GPU is essentially idle.
    if ($busySeconds -ge 1800 -and $GpuUtil -lt 2.0) {
        return @{
            server=@{ state='READY'; detail='ComfyUI API; :8188' }
            activity=@{
                state='POSSIBLY STALLED'
                detail=('queue_remaining={0}; busy {1}; GPU {2}%' -f `
                    $remaining, (Format-Elapsed $mem.busy_since), [int]$GpuUtil)
            }
        }
    }

    return @{
        server=@{ state='READY'; detail='ComfyUI API; :8188' }
        activity=@{
            state='PROCESSING'
            detail=('queue_remaining={0}; active for {1}' -f `
                $remaining, (Format-Elapsed $mem.busy_since))
        }
    }
}

function Get-AceState([double]$GpuUtil) {
    if (-not (Test-Tcp (Get-PortalPort 'acestep'))) {
        Update-BusyMemory 'ace' $false 'offline' | Out-Null
        return @{
            server=@{ state='STOPPED'; detail='on-demand; :8001' }
            activity=@{ state='OFFLINE'; detail='starts automatically when a music task needs it' }
        }
    }

    $health = Get-Json (Get-PortalServiceUrl 'acestep' '/health') 1
    if ($null -eq $health) {
        $mem = $ActivityMemory.ace
        $state = if ($null -ne $mem.busy_since -and ((Get-Date)-$mem.busy_since).TotalSeconds -gt 30) {
            'POSSIBLY STALLED'
        } else { 'STARTING' }

        return @{
            server=@{ state='PORT OPEN'; detail='ACE-Step port open; API unavailable' }
            activity=@{ state=$state; detail='health endpoint is not responding' }
        }
    }

    # /v1/stats is an official, compact endpoint that reports queue/job counts.
    $stats = Get-Json (Get-PortalServiceUrl 'acestep' '/v1/stats') 1
    if ($null -eq $stats) {
        return @{
            server=@{ state='READY'; detail='ACE-Step API; :8001' }
            activity=@{ state='MONITORING UNAVAILABLE'; detail='/v1/stats did not respond' }
        }
    }

    $running = 0
    $queued = 0
    $failed = 0
    $succeeded = 0
    $queueSize = 0
    try { $running = [int]$stats.data.jobs.running } catch {}
    try { $queued = [int]$stats.data.jobs.queued } catch {}
    try { $failed = [int]$stats.data.jobs.failed } catch {}
    try { $succeeded = [int]$stats.data.jobs.succeeded } catch {}
    try { $queueSize = [int]$stats.data.queue_size } catch {}

    $busy = ($running -gt 0 -or $queued -gt 0 -or $queueSize -gt 0)
    $fingerprint = ('{0}|{1}|{2}|{3}|{4}' -f $running,$queued,$queueSize,$failed,$succeeded)
    $mem = Update-BusyMemory 'ace' $busy $fingerprint

    if (-not $busy) {
        return @{
            server=@{ state='READY'; detail='ACE-Step API; :8001' }
            activity=@{
                state='IDLE'
                detail=('running=0; queued=0; succeeded={0}; failed={1}' -f $succeeded,$failed)
            }
        }
    }

    $busySeconds = ((Get-Date) - $mem.busy_since).TotalSeconds
    if ($busySeconds -ge 1800 -and $GpuUtil -lt 2.0) {
        return @{
            server=@{ state='READY'; detail='ACE-Step API; :8001' }
            activity=@{
                state='POSSIBLY STALLED'
                detail=('running={0}; queued={1}; active {2}; GPU {3}%' -f `
                    $running, [Math]::Max($queued,$queueSize), `
                    (Format-Elapsed $mem.busy_since), [int]$GpuUtil)
            }
        }
    }

    if ($running -gt 0) {
        return @{
            server=@{ state='READY'; detail='ACE-Step API; :8001' }
            activity=@{
                state='PROCESSING'
                detail=('running={0}; queued={1}; active for {2}' -f `
                    $running, [Math]::Max($queued,$queueSize), `
                    (Format-Elapsed $mem.busy_since))
            }
        }
    }

    return @{
        server=@{ state='READY'; detail='ACE-Step API; :8001' }
        activity=@{
            state='QUEUED'
            detail=('{0} music job(s) waiting' -f [Math]::Max($queued,$queueSize))
        }
    }
}

function Get-InstalledState {
    $installed = [ordered]@{}

    # v15.130 deterministic science/engineering toolkit. This is not a
    # persistent service: Installed reports on-disk capability, while foreground
    # ai_tools.py science calls are surfaced by the Control Center Agent tracker.
    $scienceBridge = File-Exists 'Agent\scientific_tool_bridge.py'
    $scienceCore = File-Exists 'Scientific\science_core.py'
    $scienceRoute = File-Contains 'Agent\ai_tools.py' 'sub.add_parser("science"'
    $sciencePackagesDir = Join-Path $Root 'Runtime\ScientificPython\packages'
    $sciencePackages = $false
    if (Test-Path -LiteralPath $sciencePackagesDir) {
        $sciencePackages = $null -ne (Get-ChildItem -LiteralPath $sciencePackagesDir -Force -ErrorAction SilentlyContinue | Select-Object -First 1)
    }
    $scienceAny = $scienceBridge -or $scienceCore -or $scienceRoute -or $sciencePackages
    if ($scienceBridge -and $scienceCore -and $scienceRoute -and $sciencePackages) {
        $optional = @()
        $gmshDll = Get-ChildItem -LiteralPath (Join-Path $Root 'Runtime\ScientificPython') -Filter 'gmsh*.dll' -File -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($null -eq $gmshDll) { $optional += 'Gmsh SDK' }
        if (-not ((File-Exists 'Scientific\External\MAFFT\mafft.bat') -or (File-Exists 'Tools\MAFFT\mafft.bat'))) { $optional += 'MAFFT optional' }
        if (-not ((File-Exists 'Tools\KiCad\bin\kicad-cli.exe') -or (File-Exists 'Tools\KiCad\kicad-cli.exe'))) { $optional += 'KiCad CLI optional' }
        $detail = 'v15.130 deterministic science/engineering routes; CPU/RAM on-demand'
        if ($optional.Count -gt 0) { $detail += '; ' + ($optional -join ', ') }
        $installed.science = @{ state='INSTALLED'; detail=$detail }
    } elseif ($scienceAny) {
        $installed.science = @{ state='PARTIAL'; detail='v15.130 science route/bridge/core/runtime incomplete' }
    } else {
        $installed.science = @{ state='NOT INSTALLED'; detail='deterministic Science / Engineering toolkit not detected' }
    }

    $voiceRuntime = (File-Exists 'Runtime\BootstrapPython\python.exe') -and (File-Exists 'Voice\Qwen3-TTS\.venv\Lib\site-packages\qwen_tts\__init__.py')
    $voiceDesign = File-Exists 'Voice\Qwen3-TTS\models\Qwen3-TTS-12Hz-1.7B-VoiceDesign'
    $voiceBase = File-Exists 'Voice\Qwen3-TTS\models\Qwen3-TTS-12Hz-1.7B-Base'

    if ($voiceRuntime -and $voiceDesign -and $voiceBase) {
        $installed.voice = @{ state='INSTALLED'; detail='local runtime + core voice models' }
    } elseif ($voiceRuntime -or $voiceDesign -or $voiceBase) {
        $installed.voice = @{ state='PARTIAL'; detail='run Setup\Qwen3-TTS repair' }
    } else {
        $installed.voice = @{ state='NOT INSTALLED'; detail='run Setup\Qwen3-TTS installer' }
    }

    $official = File-Exists 'Generative\ComfyUI_windows_portable\ComfyUI\models\diffusion_models\flux-2-klein-base-9b-fp8.safetensors'
    $alt = File-Exists 'Generative\ComfyUI_windows_portable\ComfyUI\models\diffusion_models\flux-2-klein-base-9b-uncensored.safetensors'

    $installed.fluxOfficial = if ($official) {
        @{ state='INSTALLED'; detail='9B FP8 checkpoint detected' }
    } else {
        @{ state='MISSING'; detail='official checkpoint not detected' }
    }

    $installed.fluxAlt = if ($alt) {
        @{ state='INSTALLED'; detail='alternative checkpoint detected' }
    } else {
        @{ state='MISSING'; detail='alternative checkpoint not detected' }
    }

    $imageWorkflows = Files-Exist @(
        'Workflows\API\Flux2_Klein_9B_T2I_Official_FP8.json',
        'Workflows\API\Flux2_Klein_9B_Image_Edit_Official_FP8.json'
    )
    $installed.imageEdit = if ($imageWorkflows -and $official) {
        @{ state='INSTALLED'; detail='generation + whole-image editing' }
    } else {
        @{ state='PARTIAL'; detail='checkpoint/workflow missing' }
    }

    $inpaintWorkflows = Files-Exist @(
        'Workflows\API\Flux2_Klein_9B_Inpaint_Official_FP8.json',
        'Workflows\API\Flux2_Klein_9B_Inpaint_Uncensored.json'
    )
    $sam2Plugin = File-Exists 'Generative\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI-SAM2'
    $samDir = Join-Path $Root 'Generative\ComfyUI_windows_portable\ComfyUI\models\sam2'
    $gdinoDir = Join-Path $Root 'Generative\ComfyUI_windows_portable\ComfyUI\models\grounding-dino'
    $samModel = $false
    $gdinoModel = $false

    if (Test-Path -LiteralPath $samDir) {
        $samModel = $null -ne (Get-ChildItem -LiteralPath $samDir -File -ErrorAction SilentlyContinue | Select-Object -First 1)
    }
    if (Test-Path -LiteralPath $gdinoDir) {
        $gdinoModel = $null -ne (Get-ChildItem -LiteralPath $gdinoDir -File -ErrorAction SilentlyContinue | Select-Object -First 1)
    }

    $installed.inpaint = if ($inpaintWorkflows -and $sam2Plugin -and $samModel -and $gdinoModel) {
        @{ state='INSTALLED'; detail='inpaint + GroundingDINO/SAM2 masking' }
    } elseif ($inpaintWorkflows -or $sam2Plugin) {
        @{ state='PARTIAL'; detail='workflow/plugin/model incomplete' }
    } else {
        @{ state='MISSING'; detail='inpainting/masking not detected' }
    }

    $wanHigh = File-Exists 'Generative\ComfyUI_windows_portable\ComfyUI\models\diffusion_models\wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors'
    $wanLow = File-Exists 'Generative\ComfyUI_windows_portable\ComfyUI\models\diffusion_models\wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors'
    $wanWorkflow = File-Exists 'Workflows\API\Wan2.2_14B_I2V_Official.json'
    $wanReady = $wanHigh -and $wanLow -and $wanWorkflow
    $installed.video = if ($wanReady) {
        @{ state='INSTALLED'; detail='Wan 2.2 14B I2V' }
    } else {
        @{ state='PARTIAL'; detail='Wan model/workflow incomplete' }
    }

    # MuseTalk 1.5 is a one-shot dialogue-video component rather than a
    # persistent localhost service, so it belongs in Installed Components.
    $museRuntime = File-Exists 'Video\MuseTalk\.venv\Scripts\python.exe'
    $museBridge = File-Exists 'Agent\musetalk_bridge.py'
    $museCore = Files-Exist @(
        'Video\MuseTalk\models\musetalkV15\unet.pth',
        'Video\MuseTalk\models\musetalkV15\musetalk.json'
    )
    $museSupport = Files-Exist @(
        'Video\MuseTalk\models\whisper\config.json',
        'Video\MuseTalk\models\whisper\pytorch_model.bin',
        'Video\MuseTalk\models\whisper\preprocessor_config.json',
        'Video\MuseTalk\models\sd-vae\config.json',
        'Video\MuseTalk\models\sd-vae\diffusion_pytorch_model.bin',
        'Video\MuseTalk\models\dwpose\dw-ll_ucoco_384.pth',
        'Video\MuseTalk\models\syncnet\latentsync_syncnet.pt',
        'Video\MuseTalk\models\face-parse-bisent\79999_iter.pth',
        'Video\MuseTalk\models\face-parse-bisent\resnet18-5c106cde.pth'
    )
    $museReady = $museRuntime -and $museBridge -and $museCore -and $museSupport

    $installed.lipSync = if ($museReady) {
        @{ state='INSTALLED'; detail='MuseTalk 1.5 runtime + sync/support models' }
    } elseif ($museRuntime -or $museBridge -or $museCore -or $museSupport) {
        @{ state='PARTIAL'; detail='MuseTalk runtime/bridge/model set incomplete' }
    } else {
        @{ state='MISSING'; detail='run Installers\Install_MuseTalk15.bat' }
    }

    # Track the two user-facing synchronized-dialogue routes separately from
    # raw MuseTalk installation. dialogue-video also requires Wan I2V, while
    # video-dialogue can operate on an existing video without Wan.
    $hasDialogueVideo = File-Contains 'Agent\ai_tools.py' 'sub.add_parser("dialogue-video"'
    $hasVideoDialogue = File-Contains 'Agent\ai_tools.py' 'sub.add_parser("video-dialogue"'
    $voiceReady = $voiceRuntime -and $voiceDesign -and $voiceBase

    $dialogueVideoReady = $voiceReady -and $museReady -and $wanReady -and $hasDialogueVideo
    $videoDialogueReady = $voiceReady -and $museReady -and $hasVideoDialogue

    if ($dialogueVideoReady -and $videoDialogueReady) {
        $installed.dialogueVideo = @{
            state='INSTALLED'
            detail='dialogue-video + video-dialogue synchronized speech routes'
        }
    } elseif ($videoDialogueReady) {
        $installed.dialogueVideo = @{
            state='PARTIAL'
            detail='video-dialogue ready; still-image dialogue-video incomplete'
        }
    } elseif ($dialogueVideoReady) {
        $installed.dialogueVideo = @{
            state='PARTIAL'
            detail='dialogue-video ready; existing-video dialogue route incomplete'
        }
    } elseif ($museReady -or $hasDialogueVideo -or $hasVideoDialogue) {
        $installed.dialogueVideo = @{
            state='PARTIAL'
            detail='pipeline present but voice/Wan/MuseTalk dependency incomplete'
        }
    } else {
        $installed.dialogueVideo = @{
            state='MISSING'
            detail='synchronized dialogue routes not detected'
        }
    }

    $aceRoot = File-Exists 'Music\ACE-Step-1.5\acestep'
    $aceModels = File-Exists 'Music\ACE-Step-1.5\checkpoints'
    $installed.music = if ($aceRoot -and $aceModels) {
        @{ state='INSTALLED'; detail='ACE-Step 1.5 local runtime' }
    } else {
        @{ state='PARTIAL'; detail='ACE-Step runtime/checkpoints incomplete' }
    }

    $diffusion = Inventory `
        'Generative\ComfyUI_windows_portable\ComfyUI\models\diffusion_models' `
        @('*.safetensors','*.gguf')

    $loras = Inventory `
        'Generative\ComfyUI_windows_portable\ComfyUI\models\loras' `
        @('*.safetensors','*.pt','*.pth')

    @{
        components=$installed
        diffusionModels=$diffusion
        loras=$loras
    }
}

Log ('Status worker v15.130 started; owner PID ' + $OwnerPid)

while (Owner-Alive) {
    $force = Test-Path -LiteralPath $ForcePath
    if ($force) {
        Remove-Item -LiteralPath $ForcePath -Force -ErrorAction SilentlyContinue
    }

    try {
        # Props is intentionally low-frequency; metrics/queue/stats are compact.
        if ($force) {
            $script:LastGpuPoll = [DateTime]::MinValue
            $script:LastPropsPoll = [DateTime]::MinValue
            $script:LastInventoryPoll = [DateTime]::MinValue
        }

        # Prime/refresh Qwen props before GPU model reporting.
        if (((Get-Date) - $LastPropsPoll).TotalSeconds -ge $PropsPollSeconds -or $null -eq $CachedQwenProps) {
            if (Test-Tcp (Get-PortalPort 'qwen')) {
                $script:CachedQwenProps = Get-Json (Get-PortalServiceUrl 'qwen' '/props') 1
            } else {
                $script:CachedQwenProps = $null
            }
            $script:LastPropsPoll = Get-Date
        }

        $gpu = Get-GpuState
        $qwen = Get-QwenState
        $comfy = Get-ComfyState ([double]$gpu.utilization)
        $ace = Get-AceState ([double]$gpu.utilization)

        # PortableAI media preview server is a tiny localhost-only static server.
        # A single compact health request is enough to track it.
        if (Test-Http (Get-PortalServiceUrl 'preview' '/__health__') 1) {
            $mediaServer = @{ state='READY'; detail='Outputs preview server; :8765' }
            $mediaActivity = @{ state='IDLE'; detail='serves generated Outputs on demand' }
        } elseif (Test-Tcp (Get-PortalPort 'preview')) {
            $mediaServer = @{ state='PORT OPEN'; detail='preview port open; health unavailable' }
            $mediaActivity = @{ state='STARTING'; detail='waiting for preview health endpoint' }
        } else {
            $mediaServer = @{ state='STOPPED'; detail='localhost preview server; :8765' }
            $mediaActivity = @{ state='OFFLINE'; detail='starts with PortableAI Startup' }
        }

        $openGui = if (@(Get-Process -Name 'OpenGUI' -ErrorAction SilentlyContinue).Count -gt 0) {
            @{ state='RUNNING'; detail='desktop host' }
        } else {
            @{ state='STOPPED'; detail='desktop host' }
        }

        if ($null -eq $InstalledCache -or `
            ((Get-Date) - $LastInventoryPoll).TotalSeconds -ge $InventoryPollSeconds) {
            $script:InstalledCache = Get-InstalledState
            $script:LastInventoryPoll = Get-Date
            Log 'Completed low-frequency installed-component inventory scan.'
        }

        $payload = [ordered]@{
            timestamp=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            poll_seconds=$PollSeconds
            servers=[ordered]@{
                qwen=$qwen.server
                comfy=$comfy.server
                ace=$ace.server
                media=$mediaServer
                opengui=$openGui
            }
            activity=[ordered]@{
                qwen=$qwen.activity
                comfy=$comfy.activity
                ace=$ace.activity
                media=$mediaActivity
            }
            gpu=$gpu
            installed=$InstalledCache
        }

        $payload | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $TempPath -Encoding UTF8
        Move-Item -LiteralPath $TempPath -Destination $StatusPath -Force
    } catch {
        Log ('Probe error: ' + $_.Exception.Message)
    }

    Start-Sleep -Seconds $PollSeconds
}

Log 'Owner exited; status worker stopping.'
