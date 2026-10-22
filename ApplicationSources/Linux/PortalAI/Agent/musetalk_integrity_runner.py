from __future__ import annotations
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference

"""PortableAI MuseTalk 1.5 integrity runner, portable Python 3.10 edition.

The runner never writes into the MuseTalk checkout.  When the installed upstream
source exactly matches the known MuseTalk 1.5 structure, a strict in-memory
hardening transform is applied.  If the checkout is a compatible fork or a
partially reformatted variant, postflight validation remains available only when
no unhandled os.system calls remain. Unknown shell-string source fails preflight.
The supported transform ignores trailing whitespace and checks every composed
frame and ffmpeg result. Runtime packages and job data remain on the SSD.
"""

import ast
import glob
import os
import subprocess
import sys
import time
from pathlib import Path

VERSION = "2026.10.10"
MARK = "PORTABLEAI_MUSETALK_FRAME_INTEGRITY_v15_128E"
OLD_IN_MEMORY_MARKS = (
    "PORTABLEAI_MUSETALK_FRAME_INTEGRITY_v15_128B",
    "PORTABLEAI_MUSETALK_FRAME_INTEGRITY_v15_128C",
)
LEGACY_DIRECT_MARK = "PORTABLEAI_MUSETALK_OUTPUT_INTEGRITY_v15_128"


def root_dir() -> Path:
    env = os.environ.get("PORTABLEAI_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parent.parent


def locate_upstream(root: Path) -> tuple[Path, Path]:
    work_candidates = [
        root / "Video" / "MuseTalk",
        root / "MuseTalk",
        root / "Video" / "MuseTalk-1.5",
        root / "Generative" / "MuseTalk",
    ]
    found: list[tuple[Path, Path]] = []
    for work in work_candidates:
        p = work / "scripts" / "inference.py"
        if p.exists():
            found.append((work, p))
    if not found:
        for p in root.glob("**/MuseTalk/scripts/inference.py"):
            found.append((p.parent.parent, p))
    unique: list[tuple[Path, Path]] = []
    seen: set[str] = set()
    for work, p in found:
        key = str(p.resolve()).lower()
        if key not in seen:
            seen.add(key)
            unique.append((work.resolve(), p.resolve()))
    if len(unique) != 1:
        raise RuntimeError(
            "Expected exactly one MuseTalk scripts/inference.py; found "
            + repr([str(p) for _, p in unique])
        )
    return unique[0]


def _strict_clean_transform(text: str) -> str | None:
    """Return hardened source only for the exact source layout we have verified."""
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    if "import subprocess" not in text or "import glob" not in text:
        return None
    old_comp = '''                try:\n                    res_frame = cv2.resize(res_frame.astype(np.uint8), (x2-x1, y2-y1))\n                except:\n                    continue\n\n                # Merge results with version-specific parameters\n                if args.version == "v15":\n                    combine_frame = get_image(ori_frame, res_frame, [x1, y1, x2, y2], mode=args.parsing_mode, fp=fp)\n                else:\n                    combine_frame = get_image(ori_frame, res_frame, [x1, y1, x2, y2], fp=fp)\n                cv2.imwrite(f"{result_img_save_path}/{str(i).zfill(8)}.png", combine_frame)\n'''
    old_ff = '''            # Save prediction results\n            temp_vid_path = f"{temp_dir}/temp_{input_basename}_{audio_basename}.mp4"\n            cmd_img2video = f"ffmpeg -y -v warning -r {fps} -f image2 -i {result_img_save_path}/%08d.png -vcodec libx264 -vf format=yuv420p -crf 18 {temp_vid_path}"\n            print("Video generation command:", cmd_img2video)\n            os.system(cmd_img2video)\n\n            cmd_combine_audio = f"ffmpeg -y -v warning -i {audio_path} -i {temp_vid_path} {output_vid_name}"\n            print("Audio combination command:", cmd_combine_audio)\n            os.system(cmd_combine_audio)\n'''
    old_exc = '''        except Exception as e:\n            print("Error occurred during processing:", e)\n'''
    if old_comp not in text or old_ff not in text or old_exc not in text:
        return None

    new_comp = f'''                # {MARK}\n                # Never silently drop a composite frame and never substitute a source\n                # frame as a fake lip-synced success. Fail at the real blend/write stage.\n                try:\n                    target_w = int(x2 - x1)\n                    target_h = int(y2 - y1)\n                    if target_w <= 0 or target_h <= 0:\n                        raise ValueError(f"invalid bbox target {{target_w}}x{{target_h}}")\n                    res_frame = cv2.resize(res_frame.astype(np.uint8), (target_w, target_h))\n                    if args.version == "v15":\n                        combine_frame = get_image(ori_frame, res_frame, [x1, y1, x2, y2], mode=args.parsing_mode, fp=fp)\n                    else:\n                        combine_frame = get_image(ori_frame, res_frame, [x1, y1, x2, y2], fp=fp)\n                except Exception as frame_exc:\n                    raise RuntimeError(\n                        f"MuseTalk composite frame {{i}} failed before write; bbox={{bbox!r}}, "\n                        f"target={{int(x2-x1)}}x{{int(y2-y1)}}, "\n                        f"generated_shape={{getattr(res_frame, 'shape', None)}}, "\n                        f"generated_type={{type(res_frame).__name__}}"\n                    ) from frame_exc\n                if combine_frame is None:\n                    raise RuntimeError(f"MuseTalk blend returned None at composite frame {{i}}")\n                frame_path = os.path.join(result_img_save_path, f"{{i:08d}}.png")\n                if not cv2.imwrite(frame_path, combine_frame):\n                    raise RuntimeError(f"OpenCV failed to write MuseTalk composite frame: {{frame_path}}")\n'''
    new_ff = '''            # Validate the composite sequence before invoking ffmpeg.\n            generated_frames = sorted(glob.glob(os.path.join(result_img_save_path, "*.png")))\n            expected_frames = len(res_frame_list)\n            if not generated_frames:\n                source_count = len(input_img_list) if input_img_list is not None else 0\n                raise RuntimeError(\n                    f"MuseTalk inference produced zero composite PNG frames in {result_img_save_path}; "\n                    f"source_frames={source_count}; inferred_frames={expected_frames}"\n                )\n            if len(generated_frames) != expected_frames:\n                raise RuntimeError(\n                    f"MuseTalk composite sequence is incomplete: wrote {len(generated_frames)} of "\n                    f"{expected_frames} expected frames in {result_img_save_path}"\n                )\n\n            temp_vid_path = f"{temp_dir}/temp_{input_basename}_{audio_basename}.mp4"\n            cmd_img2video = [\n                "ffmpeg", "-y", "-v", "warning", "-r", str(fps), "-f", "image2",\n                "-i", os.path.join(result_img_save_path, "%08d.png"),\n                "-vcodec", "libx264", "-vf", "format=yuv420p", "-crf", "18", temp_vid_path,\n            ]\n            print("Video generation command:", subprocess.list2cmdline(cmd_img2video))\n            subprocess.run(cmd_img2video, check=True)\n            if not os.path.isfile(temp_vid_path) or os.path.getsize(temp_vid_path) <= 0:\n                raise RuntimeError(f"ffmpeg returned without a usable MuseTalk temp video: {temp_vid_path}")\n\n            cmd_combine_audio = [\n                "ffmpeg", "-y", "-v", "warning", "-i", audio_path, "-i", temp_vid_path, output_vid_name\n            ]\n            print("Audio combination command:", subprocess.list2cmdline(cmd_combine_audio))\n            subprocess.run(cmd_combine_audio, check=True)\n            if not os.path.isfile(output_vid_name) or os.path.getsize(output_vid_name) <= 0:\n                raise RuntimeError(f"ffmpeg returned without a usable MuseTalk output video: {output_vid_name}")\n'''
    new_exc = '''        except Exception as e:\n            print("Error occurred during processing:", e)\n            # PortableAI: propagate task failure so the bridge cannot accept exit-code 0.\n            raise\n'''

    old_extract = '                cmd = f"ffmpeg -v fatal -i {video_path} -start_number 0 {save_dir_full}/%08d.png"\n                os.system(cmd)'
    if old_extract not in text:
        return None
    out = text.replace(old_extract, '                subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video_path, "-start_number", "0", os.path.join(save_dir_full, "%08d.png")], check=True)', 1)
    # Only the compositing loop has ori_frame; preprocessing still uses frame.
    old_blend = '                    y2 = min(y2, frame.shape[0])\n                try:'
    out = out.replace(old_blend, '                    y2 = min(y2, ori_frame.shape[0])\n                try:', 1)
    out = out.replace('            shutil.rmtree(save_dir_full)', '            if get_file_type(video_path) == "video":\n                shutil.rmtree(save_dir_full)', 1)
    out = out.replace(old_comp, new_comp, 1)
    out = out.replace(old_ff, new_ff, 1)
    out = out.replace(old_exc, new_exc, 1)
    ast.parse(out)
    return out


def patch_source(text: str) -> tuple[str, str]:
    """Choose the strongest safe mode without rejecting harmless source drift."""
    ast.parse(text)
    if MARK in text:
        return text, "already-v15.128e"
    if any(mark in text for mark in OLD_IN_MEMORY_MARKS):
        return text, "prior-in-memory-hardening"
    if LEGACY_DIRECT_MARK in text:
        # The older direct patch modified the checkout itself. Do not stack another
        # source rewrite on top of it; execution + postflight validation remains active.
        return text, "legacy-direct-v15.128"

    strict = _strict_clean_transform(text)
    if strict is not None:
        return strict, "clean-upstream-in-memory-hardening"

    # v15.128c failed here because it treated a source-layout mismatch as fatal.
    # Source drift is not itself an integrity failure.  Execute the installed source
    # unchanged, then validate the unique current job and let the bridge reject any
    # missing/stale final artifact. This mode cannot confuse video/ with video_audio/.
    return text, "compatible-source-postflight-validation"


def _recent_job_diagnostic(started: float) -> tuple[str, bool]:
    roots = [private_path(root_dir(), 'Cache/MuseTalk')]
    jobs: list[tuple[float, Path]] = []
    seen: set[str] = set()
    for base in roots:
        try:
            key = str(base.resolve()).lower()
        except Exception:
            key = str(base).lower()
        if key in seen or not base.is_dir():
            continue
        seen.add(key)
        try:
            for job in base.glob("musetalk_*"):
                try:
                    mt = job.stat().st_mtime
                except OSError:
                    continue
                if mt >= started - 10.0:
                    jobs.append((mt, job))
        except OSError:
            pass
    jobs.sort(key=lambda x: x[0], reverse=True)
    lines: list[str] = []
    fresh_final = False
    for _, job in jobs[:4]:
        result = job / "results" / "v15"
        if not result.is_dir():
            continue
        parts: list[str] = []
        try:
            for d in sorted((p for p in result.iterdir() if p.is_dir()), key=lambda p: p.name.lower()):
                try:
                    n = sum(1 for _ in d.glob("*.png"))
                except OSError:
                    n = -1
                parts.append(f"{d.name}={n} PNG")
            temps = []
            finals = []
            for p in result.glob("*.mp4"):
                if not p.is_file():
                    continue
                try:
                    is_fresh = p.stat().st_mtime >= started - 5.0 and p.stat().st_size > 0
                except OSError:
                    is_fresh = False
                if p.name.startswith("temp_"):
                    temps.append(p.name)
                else:
                    finals.append(p.name)
                    fresh_final = fresh_final or is_fresh
            lines.append(
                f"MuseTalk job {job}: result_dirs[{', '.join(parts) or 'none'}]; "
                f"temp_mp4={temps or 'none'}; final_mp4={finals or 'none'}"
            )
        except OSError:
            continue
    if not lines:
        return "MuseTalk postflight: no current results/v15 job directory was found for bounded inspection.", False
    return "\n".join(lines), fresh_final


def main() -> int:
    root = root_dir()
    work, upstream = locate_upstream(root)
    source = upstream.read_text(encoding="utf-8", errors="strict")
    executable, mode = patch_source(source)
    tree = ast.parse(executable)
    if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and isinstance(n.func.value, ast.Name) and n.func.value.id == "os"
           and n.func.attr == "system" for n in ast.walk(tree)):
        raise RuntimeError("MuseTalk source has unhandled shell-string commands; portable path validation required")

    if "--portableai-preflight" in sys.argv[1:]:
        print(f"PRECHECK PASS: MuseTalk integrity runner compatible with {upstream}; mode={mode}")
        if mode == "compatible-source-postflight-validation":
            print("PRECHECK NOTE: installed MuseTalk source layout differs from the strict known template; "
                  "PortableAI will execute it unchanged and enforce fresh-artifact postflight validation.")
        return 0

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import musetalk_runtime
    musetalk_runtime.activate(root)
    started = time.time()
    print(f"PortableAI MuseTalk integrity runner v{VERSION}: {upstream}; mode={mode}", flush=True)
    os.chdir(work)
    if str(work) not in sys.path:
        sys.path.insert(0, str(work))
    sys.argv[0] = str(upstream)
    ns = {
        "__name__": "__main__",
        "__file__": str(upstream),
        "__package__": None,
        "__cached__": None,
    }
    exec(compile(executable, str(upstream), "exec"), ns, ns)

    # Unknown/reformatted sources can swallow their own internal exception and exit 0.
    # Inspect the unique recent job after execution and turn a missing final artifact
    # into a real runner failure with frame-directory counts.
    diagnostic, fresh_final = _recent_job_diagnostic(started)
    if mode == "compatible-source-postflight-validation" and "result_dirs[" in diagnostic and not fresh_final:
        raise RuntimeError(
            "MuseTalk source returned without a fresh final MP4. "
            "The source was intentionally not rewritten because its layout differs from the verified template.\n"
            + diagnostic
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
