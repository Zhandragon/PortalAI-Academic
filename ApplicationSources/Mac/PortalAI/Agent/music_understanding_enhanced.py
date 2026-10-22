from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from music_understanding_bridge import MusicUnderstandingBridge as LegacyMusicUnderstandingBridge
from media_paths import media_reference, media_output
from runtime_policy import portable_env

VERSION = "15.111"

_GENRE_LABELS = [
    "pop", "rock", "metal", "punk", "alternative rock", "indie rock", "hard rock",
    "hip hop", "rap", "trap", "R&B", "soul", "funk", "disco", "jazz", "blues",
    "classical", "orchestral", "ambient", "electronic", "EDM", "house", "techno",
    "trance", "drum and bass", "dubstep", "synthwave", "industrial", "folk",
    "country", "bluegrass", "reggae", "ska", "latin", "world music", "soundtrack",
    "experimental", "lo-fi", "acoustic", "gospel"
]

_INSTRUMENT_LABELS = [
    "male singing voice", "female singing voice", "choir", "spoken voice",
    "acoustic guitar", "electric guitar", "distorted electric guitar", "bass guitar",
    "upright bass", "drum kit", "electronic drums", "percussion", "piano",
    "electric piano", "organ", "synthesizer", "synth pad", "sampler", "strings",
    "violin", "viola", "cello", "orchestra", "brass", "trumpet", "trombone",
    "saxophone", "clarinet", "flute", "harmonica", "harp", "banjo", "mandolin",
    "accordion", "bells"
]


def _root_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _private_python(root: Path) -> Path:
    if os.name!='nt':
        from platform_runtime import python_path
        return python_path(root)
    return root / "MusicUnderstanding" / "runtime" / "python.exe"


def _driver(root: Path) -> Path:
    return root / "MusicUnderstanding" / "runtime_driver.py"


def _question_wants_lyrics(question: str | None) -> bool:
    q = (question or "").lower()
    keys = ("lyric", "words", "transcrib", "what is being sung", "what are they singing", "singing")
    return any(k in q for k in keys)


def _child_env(root: Path) -> dict[str, str]:
    env = portable_env(root)
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__"):
        env.pop(key, None)
    env["PYTHONNOUSERSITE"] = "1"
    env["PORTABLEAI_ROOT"] = str(root)
    env["HF_HOME"] = str(root / "MusicUnderstanding" / "cache" / "huggingface")
    env["HUGGINGFACE_HUB_CACHE"] = str(root / "MusicUnderstanding" / "cache" / "huggingface" / "hub")
    env["TRANSFORMERS_CACHE"] = str(root / "MusicUnderstanding" / "cache" / "huggingface" / "transformers")
    env["TORCH_HOME"] = str(root / "MusicUnderstanding" / "cache" / "torch")
    ffmpeg = root / "Tools" / "ffmpeg" / "bin"
    if ffmpeg.is_dir():
        env["PATH"] = str(ffmpeg) + os.pathsep + env.get("PATH", "")
    return env


def _run_json(cmd: list[str], timeout: int, root: Path) -> dict[str, Any]:
    if os.name != 'nt':
        from music_understanding_runtime import run
        cp = run(root, cmd[2:], timeout)
    else:
        cp = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=timeout,
            cwd=str(root), env=_child_env(root),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout or f"exit code {cp.returncode}").strip()
        raise RuntimeError(detail[-12000:])
    text = (cp.stdout or "").strip()
    if not text:
        return {}
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            return json.loads(line)
    return json.loads(text)


class EnhancedMusicUnderstandingBridge:
    """Combine deterministic MIR, MOSS-Music, CLAP, Demucs vocal isolation, and optional ACE lyrics evidence."""

    def __init__(self) -> None:
        self.root = _root_dir()
        self.legacy = LegacyMusicUnderstandingBridge()

    def _specialist_available(self, kind="moss") -> tuple[bool, str | None]:
        if os.name!='nt':
            from music_understanding_runtime import available
            return available(self.root, kind)
        py = _private_python(self.root)
        drv = _driver(self.root)
        moss = self.root / "MusicUnderstanding" / "models" / "MOSS-Music-8B-Instruct"
        if not py.exists():
            return False, f"private music runtime missing: {py}"
        if not drv.exists():
            return False, f"music runtime driver missing: {drv}"
        if kind == 'moss' and not (moss / "config.json").exists():
            return False, f"MOSS-Music model missing/incomplete: {moss}"
        if kind == 'separate-vocals':
            from windows_demucs import model_path
            try: model_path(self.root, verify=False)
            except (OSError, ValueError, RuntimeError) as exc: return False, str(exc)
        return True, None

    def understand(
        self,
        input_path: str,
        question: str | None = None,
        semantic: bool = True,
        semantic_device: str = "cpu",
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        # Authenticate references before optional analyzers catch errors and
        # fall back; a privacy denial must not enter a different decoder path.
        input_path = str(media_reference(self.root, input_path))
        if output_dir is not None:
            output_dir = str(media_output(self.root, output_dir))
        result: dict[str, Any] = {}
        warnings: list[str] = []

        # Keep the established deterministic/MIR path, but disable its old optional
        # CLAP layer so semantic work has exactly one controlled implementation.
        try:
            legacy = self.legacy.understand(
                input_path,
                question=question,
                semantic=False,
                semantic_device=semantic_device,
                output_dir=output_dir,
            )
            if isinstance(legacy, dict):
                result.update(legacy)
                result["deterministic_analysis"] = legacy
        except Exception as exc:
            warnings.append(f"deterministic analyzer failed: {type(exc).__name__}: {exc}")

        def available(kind):
            ready, why = self._specialist_available(kind)
            if not ready:
                warnings.append(kind + ': ' + (why or 'specialist runtime unavailable'))
            return ready

        py = str(_private_python(self.root))
        driver = str(_driver(self.root))
        audio = str(media_reference(self.root, input_path))
        wants_lyrics = _question_wants_lyrics(question)

        if question:
            prompt = (
                "Analyze the supplied music carefully and answer the user's question directly. "
                "Ground the answer in the audio. Identify likely genre/style, audible instruments/voices, "
                "and relevant structure or production traits when useful. If the question asks for lyrics, "
                "transcribe only words you can support from the audio and mark uncertainty rather than inventing text. "
                f"User question: {question}"
            )
        else:
            prompt = (
                "Give a compact but detailed analysis of this music. Identify likely primary and secondary genre/style, "
                "audible instruments and voices, vocal characteristics, song structure, production traits, mood, and "
                "notable musical events. Do not invent lyrics; only mention words if clearly intelligible."
            )

        lyric_audio = audio
        if wants_lyrics and available('separate-vocals'):
            try:
                sep = _run_json(
                    [py, driver, "separate-vocals", "--audio", audio, "--device",
                     semantic_device if semantic_device in ("cpu", "cuda", "auto") else "auto"],
                    timeout=1800,
                    root=self.root,
                )
                result["vocal_isolation"] = sep
                if isinstance(sep, dict) and sep.get("vocals_path"):
                    lyric_audio = str(sep["vocals_path"])
            except Exception as exc:
                warnings.append(f"Demucs vocal isolation unavailable; using the original mix for lyrics: {type(exc).__name__}: {exc}")
                result["vocal_isolation"] = {"available": False, "error": str(exc)}

        moss_cmd = [py, driver, "moss", "--audio", audio, "--prompt", prompt]
        if wants_lyrics:
            moss_cmd += [
                "--lyrics-audio", lyric_audio,
                "--lyrics-prompt",
                "Transcribe the sung lyrics in this audio faithfully. Preserve line/section breaks where apparent. "
                "Do not invent words for instrumental or unclear passages; mark uncertain words as [unclear].",
            ]
        if os.name != 'nt':
            moss_cmd += ['--device', semantic_device]
        if available('moss'):
            try:
                result["moss_music"] = _run_json(
                    moss_cmd, timeout=2400 if wants_lyrics else 1200, root=self.root,
                )
            except Exception as exc:
                warnings.append(f"MOSS-Music failed: {type(exc).__name__}: {exc}")

        if semantic:
            clap_model = self.root / "MusicUnderstanding" / "models" / "CLAP-larger-music"
            if (clap_model / "config.json").exists() and available('clap'):
                try:
                    clap_cmd = [
                        py, driver, "clap", "--audio", audio,
                        "--genre-labels", json.dumps(_GENRE_LABELS),
                        "--instrument-labels", json.dumps(_INSTRUMENT_LABELS),
                        "--device", semantic_device if semantic_device in ("cpu", "cuda", "auto") else "cpu",
                    ]
                    result["clap_semantics"] = _run_json(clap_cmd, timeout=420, root=self.root)
                except Exception as exc:
                    warnings.append(f"CLAP semantic analysis failed: {type(exc).__name__}: {exc}")
            else:
                warnings.append("CLAP semantic model is not installed")

        if wants_lyrics:
            ace_model = self.root / "MusicUnderstanding" / "models" / "ACE-Step-acestep-transcriber"
            if (ace_model / "config.json").exists():
                try:
                    result["ace_lyrics_fallback"] = _run_json(
                        [py, driver, "ace-lyrics", "--audio", audio],
                        timeout=1800,
                        root=self.root,
                    )
                except Exception as exc:
                    warnings.append(f"ACE-Step lyrics fallback failed: {type(exc).__name__}: {exc}")
            else:
                result["ace_lyrics_fallback"] = {
                    "installed": False,
                    "note": "ACE-Step singing-ASR fallback is not installed; any lyrics evidence must come from a successful specialist result.",
                }

        backends = []
        if isinstance(result.get('moss_music'),dict) and any(result['moss_music'].get(k) for k in ('text','analysis','lyrics')):
            backends.append('MOSS-Music')
        if wants_lyrics and isinstance(result.get("vocal_isolation"), dict) and result["vocal_isolation"].get("vocals_path"):
            backends.append("Demucs vocal isolation")
        if isinstance(result.get('clap_semantics'),dict) and result['clap_semantics'] and result['clap_semantics'].get('available') is not False:
            backends.append("CLAP")
        if isinstance(result.get('ace_lyrics_fallback'),dict) and any(result['ace_lyrics_fallback'].get(k) for k in ('text','lyrics')):
            backends.append("ACE-Step lyrics fallback")
        result['enhanced_music_understanding']=bool(backends)
        result['semantic_available']=any(name!='Demucs vocal isolation' for name in backends)
        result['semantic_backend']=' + '.join(backends) or ('deterministic-only' if result.get('deterministic_analysis') else 'unavailable')
        result['success']=bool(result.get('deterministic_analysis') or backends)
        result['partial']=bool(warnings) or not result['enhanced_music_understanding']
        if not result['success']:result['error']='No music analyzer produced a result'
        result["semantic_scores_note"] = "CLAP values are relative audio-text similarities, not calibrated probabilities."
        if warnings:
            result["warnings"] = warnings
        return result
