param(
    [string]$Root = '',
    [switch]$SkipCustomVoice,
    [switch]$VerifyOnly
)

$ErrorActionPreference = 'Stop'

if ([string]::IsNullOrWhiteSpace($Root)) {
    # This script lives at PortableAI\Setup\Qwen3-TTS.
    $Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
}
$Root = [System.IO.Path]::GetFullPath($Root).TrimEnd('\')

$Bootstrap = Join-Path $Root 'Runtime\BootstrapPython\python.exe'
$Verifier = Join-Path $Root 'Tools\verify_qwen_runtime.py'
if (-not (Test-Path -LiteralPath $Bootstrap -PathType Leaf)) {
    throw 'Bundled BootstrapPython is missing. Repair the PortalAI foundation runtime first.'
}
if (-not (Test-Path -LiteralPath $Verifier -PathType Leaf)) {
    throw 'Qwen runtime verifier is missing. Restore Tools\verify_qwen_runtime.py from PortalAI source.'
}
if ($VerifyOnly) {
    $CheckArgs = @('-B', '-I', $Verifier, '--root', $Root, '--require-gpu')
    if ($SkipCustomVoice) { $CheckArgs += '--skip-custom-voice' }
    & $Bootstrap @CheckArgs
    exit $LASTEXITCODE
}

$VoiceRoot = Join-Path $Root 'Voice\Qwen3-TTS'
$ToolsUv = Join-Path $Root 'Tools\uv'
$PortableCache = Join-Path $Root 'PortableCache\Qwen3-TTS'
$TempDir = Join-Path $PortableCache 'Temp'
$UvCache = Join-Path $PortableCache 'uv-cache'
$BasePythonDir = Join-Path $VoiceRoot 'python-base'
$VenvDir = Join-Path $VoiceRoot '.venv'
$HFCache = Join-Path $VoiceRoot 'hf_cache'
$TorchCache = Join-Path $VoiceRoot 'torch_cache'
$XdgCache = Join-Path $VoiceRoot 'cache'
$Runtime = Join-Path $Root 'Agent\.runtime'
$LogFile = Join-Path $Runtime 'qwen3_tts_install.log'

@($VoiceRoot,$ToolsUv,$PortableCache,$TempDir,$UvCache,$BasePythonDir,$HFCache,$TorchCache,$XdgCache,$Runtime) |
    ForEach-Object { New-Item -ItemType Directory -Force -Path $_ | Out-Null }

try { Start-Transcript -LiteralPath $LogFile -Append | Out-Null } catch {}

# Keep installer/package/model caches inside PortableAI.
$env:TEMP = $TempDir
$env:TMP = $TempDir
$env:UV_CACHE_DIR = $UvCache
$env:UV_PYTHON_INSTALL_DIR = $BasePythonDir
$env:UV_NO_MODIFY_PATH = '1'
$env:HF_HOME = $HFCache
$env:HUGGINGFACE_HUB_CACHE = Join-Path $HFCache 'hub'
$env:TRANSFORMERS_CACHE = Join-Path $HFCache 'transformers'
$env:TORCH_HOME = $TorchCache
$env:XDG_CACHE_HOME = $XdgCache
$env:PIP_CACHE_DIR = Join-Path $PortableCache 'pip-cache'
$env:HF_XET_HIGH_PERFORMANCE = '1'

Write-Host ''
Write-Host 'PortableAI Qwen3-TTS install / repair' -ForegroundColor Cyan
Write-Host ('Root: ' + $Root)
Write-Host ('Log:  ' + $LogFile)
Write-Host ''

try {
    $Uv = Join-Path $ToolsUv 'uv.exe'
    if (-not (Test-Path -LiteralPath $Uv)) {
        Write-Host '[1/7] Installing private uv under PortableAI\Tools\uv ...'
        $env:UV_UNMANAGED_INSTALL = $ToolsUv
        $installer = Join-Path $TempDir 'uv-install.ps1'
        Invoke-WebRequest -UseBasicParsing 'https://astral.sh/uv/install.ps1' -OutFile $installer
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installer
    } else {
        Write-Host '[1/7] Private uv already present.'
    }

    if (-not (Test-Path -LiteralPath $Uv)) {
        $foundUv = Get-ChildItem -LiteralPath $ToolsUv -Filter 'uv.exe' -Recurse -File -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $foundUv) { Copy-Item $foundUv.FullName $Uv -Force }
    }
    if (-not (Test-Path -LiteralPath $Uv)) { throw 'uv.exe could not be installed.' }

    Write-Host '[2/7] Installing private CPython 3.12 base runtime ...'
    & $Uv python install 3.12 --install-dir $BasePythonDir
    if ($LASTEXITCODE -ne 0) { throw "uv python install failed: $LASTEXITCODE" }

    $BasePyObj = Get-ChildItem -LiteralPath $BasePythonDir -Filter 'python.exe' -Recurse -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notmatch '\\.venv\\' } |
        Select-Object -First 1
    if ($null -eq $BasePyObj) { throw 'Could not locate private Python 3.12.' }
    $BasePy = $BasePyObj.FullName
    Write-Host ('Base Python: ' + $BasePy)

    Write-Host '[3/7] Creating CLEAN relocatable Qwen3-TTS virtual environment ...'
    # A venv avoids modifying uv's EXTERNALLY-MANAGED base interpreter.
    # --relocatable is specifically intended for moving the PortableAI folder.
    & $Uv venv --clear --seed --relocatable --python $BasePy $VenvDir
    if ($LASTEXITCODE -ne 0) { throw "uv venv failed: $LASTEXITCODE" }

    $VenvPy = Join-Path $VenvDir 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $VenvPy)) { throw 'Relocatable venv python.exe is missing.' }

    Write-Host '[4/7] Installing CUDA 12.6 PyTorch ...'
    & $Uv pip install --python $VenvPy --upgrade `
        --index-url 'https://download.pytorch.org/whl/cu126' `
        'torch' 'torchaudio'
    if ($LASTEXITCODE -ne 0) { throw "CUDA PyTorch install failed: $LASTEXITCODE" }

    Write-Host '[5/7] Installing Qwen3-TTS and runtime dependencies ...'
    & $Uv pip install --python $VenvPy --upgrade `
        'qwen-tts' 'huggingface_hub[cli]' 'hf_xet' 'accelerate' 'soundfile' 'pytz'
    if ($LASTEXITCODE -ne 0) { throw "qwen-tts install failed: $LASTEXITCODE" }

    Write-Host '[6/7] Verifying CUDA + qwen_tts imports ...'
    & $Bootstrap -B -I $Verifier --root $Root --require-gpu --packages-only
    if ($LASTEXITCODE -ne 0) { throw 'Qwen3-TTS environment installed, but CUDA/import verification failed.' }

    # Compatibility metadata; voice_bridge selects this same bundled base directly.
    Set-Content -LiteralPath (Join-Path $VoiceRoot 'python_relative.txt') `
        -Value '..\..\Runtime\BootstrapPython\python.exe' -Encoding UTF8

    Write-Host '[7/7] Downloading voice models into PortableAI ...'
    $Downloader = Join-Path $VoiceRoot 'download_models.py'
    if (-not (Test-Path -LiteralPath $Downloader)) {
        throw ('Missing downloader: ' + $Downloader)
    }

    if ($SkipCustomVoice) {
        $TempDownloader = Join-Path $TempDir 'download_qwen_core.py'
        $code = @'
from pathlib import Path
from huggingface_hub import snapshot_download
import os
root = Path(r"__VOICE_ROOT__")
models = root / "models"
models.mkdir(parents=True, exist_ok=True)
for repo in [
    "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign",
    "Qwen/Qwen3-TTS-12Hz-1.7B-Base",
]:
    snapshot_download(repo_id=repo, local_dir=str(models / repo.split("/")[-1]))
'@
        $code.Replace('__VOICE_ROOT__', $VoiceRoot) | Set-Content -LiteralPath $TempDownloader -Encoding UTF8
        & $VenvPy $TempDownloader
    } else {
        & $VenvPy $Downloader
    }
    if ($LASTEXITCODE -ne 0) { throw "Model download failed: $LASTEXITCODE" }

    $CheckArgs = @('-B', '-I', $Verifier, '--root', $Root, '--require-gpu')
    if ($SkipCustomVoice) { $CheckArgs += '--skip-custom-voice' }
    & $Bootstrap @CheckArgs
    if ($LASTEXITCODE -ne 0) { throw 'The installed Qwen runtime did not pass final verification.' }

    Write-Host ''
    Write-Host 'Qwen3-TTS installation / repair COMPLETE.' -ForegroundColor Green
    Write-Host ('Runtime: ' + $VenvDir)
    Write-Host ('Models:  ' + (Join-Path $VoiceRoot 'models'))
    Write-Host ''
    Write-Host 'The old uv-managed Python folder, if present, is no longer used.'
    Write-Host 'It can be removed later after voice generation is confirmed.'
    exit 0
}
catch {
    Write-Host ''
    Write-Host ('INSTALL FAILED: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host ('Detailed log: ' + $LogFile) -ForegroundColor Yellow
    exit 1
}
finally {
    try { Stop-Transcript | Out-Null } catch {}
}
