"""Short-lived CPU speech worker using only the SSD's pinned package layer."""
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import wave

from runtime_policy import ROOT, require_space
from tts_policy import tts_plan, validate_text


def offline_audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise RuntimeError("CPU speech inference is offline; network access is not part of this worker")


def verify_model(root, model, lock):
    """Require both selected voice pins; an unrelated optional voice is irrelevant."""
    root = Path(root).resolve(); model = Path(model).resolve()
    if not model.is_relative_to(root / "Voice/Piper/models"):
        raise ValueError("CPU voice model must stay in portable voice assets")
    pins = {a["dest"]: a for a in lock["assets"] if a["kind"] == "model"}
    for path in (model, Path(str(model) + ".json")):
        pin = pins.get(path.relative_to(root).as_posix())
        if pin is None: raise RuntimeError("CPU voice model integrity pin is missing")
        with path.open("rb") as stream: digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if path.stat().st_size != pin["size"] or digest != pin["sha256"]:
            raise RuntimeError("CPU voice model integrity check failed")


def main():
    gate = os.environ.get("PORTALAI_VOICE_GATE")
    if gate:
        end = time.monotonic()+15
        while not Path(gate).exists():
            if time.monotonic() >= end: raise RuntimeError("Voice parent did not release startup gate")
            time.sleep(.05)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    text = validate_text(request["text"])
    plan = tts_plan(engine="piper", language=request.get("language", "English"), voice=request.get("voice"))
    output = args.output.resolve()
    if not output.is_relative_to((private_path(ROOT, "Outputs")).resolve()): raise ValueError("CPU speech output must stay under portable Outputs")
    model = Path(plan["model_path"])
    lock = json.loads((ROOT/"Agent/voice_assets.json").read_text())
    verify_model(ROOT, model, lock)
    sys.path[:0]=[str(ROOT/'Voice/Piper/packages')] if os.name=='nt' else [str(ROOT/'Runtime/LinuxPackages/extras'),str(ROOT/'Runtime/LinuxPackages/media')]
    sys.addaudithook(offline_audit)
    import onnxruntime as ort
    from piper import PiperVoice
    from piper.config import PiperConfig, SynthesisConfig
    from piper.phonemize_espeak import ESPEAK_DATA_DIR
    ort.disable_telemetry_events()
    options = ort.SessionOptions(); options.intra_op_num_threads = min(4, os.cpu_count() or 1); options.inter_op_num_threads = 1
    config = json.loads(Path(str(model)+".json").read_text(encoding="utf-8"))
    voice = PiperVoice(config=PiperConfig.from_dict(config), session=ort.InferenceSession(str(model), sess_options=options,
                       providers=["CPUExecutionProvider"]), espeak_data_dir=ESPEAK_DATA_DIR, download_dir=ROOT/"Cache/piper")
    started = time.monotonic(); frames = 0
    require_space(ROOT, 32*1024**2, for_outputs=True)
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(voice.config.sample_rate)
        for chunk in voice.synthesize(text, syn_config=SynthesisConfig()):
            data = chunk.audio_int16_bytes
            if frames*2+len(data) > 32*1024**2: raise RuntimeError("CPU speech exceeds its 32 MiB output limit")
            require_space(ROOT, len(data), for_outputs=True)
            wav.writeframes(data); frames += len(data)//2
    if not frames: raise RuntimeError("Voice produced no audio")
    print(json.dumps({"success": True, "engine": "piper", "device": "cpu", "voice": plan["voice"],
                      "sample_rate": voice.config.sample_rate, "duration_seconds": frames/voice.config.sample_rate,
                      "synthesis_seconds": time.monotonic()-started, "providers": voice.session.get_providers()}), flush=True)


if __name__ == "__main__":
    from voice_memory import VoiceMemoryError
    try:
        main()
    except VoiceMemoryError as exc:
        print(json.dumps(exc.payload(), ensure_ascii=True), flush=True)
        raise SystemExit(10)
