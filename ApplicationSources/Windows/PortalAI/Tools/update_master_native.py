from __future__ import annotations

import argparse
import re
import shutil
import time
from pathlib import Path

MARKER = "PORTABLEAI_NATIVE_FRONTEND_POLICY_v15_93"
PATTERN = re.compile(r"^PortableAI_Master_Instructions_v(\d+)\.(txt|md)$", re.I)


def latest_master(root: Path) -> tuple[Path, int]:
    found = []
    for p in root.glob("PortableAI_Master_Instructions_v*.*"):
        m = PATTERN.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    if not found:
        raise FileNotFoundError("No PortableAI_Master_Instructions_v*.txt/md file was found.")
    found.sort(key=lambda x: x[0])
    n, p = found[-1]
    return p, n


def frontend_neutralize(text: str) -> str:
    replacements = [
        ("Keep this file under the OpenGUI custom-instruction character limit.",
         "Keep this file compact enough to leave ample model context for PortableAI Native Chat."),
        ("enumerate generic OpenGUI tools", "enumerate generic host tools"),
        ("Do not enumerate OpenGUI read/write/shell tools first.", "Do not enumerate generic host read/write/shell tools first."),
        ("PortableAI/OpenGUI owns command-specific timeout policy.", "PortableAI Native Chat owns command-specific timeout policy."),
        ("Host timeouts are managed by PortableAI/OpenGUI.", "Host timeouts are managed by PortableAI Native Chat."),
        ("Qwen-powered OpenGUI conversation", "Qwen-powered PortableAI Native Chat conversation"),
        ("so OpenGUI renders the actual image inline", "so PortableAI Native Chat renders the actual media inline"),
        ("so OpenGUI renders the actual image inline.", "so PortableAI Native Chat renders the actual media inline."),
        ("from OpenGUI even when the local server is healthy", "from the frontend even when the local server is healthy"),
        ("OpenGUI failed to launch a URL", "the frontend failed to launch a URL"),
        ("OpenGUI to hit its provider timeout", "the frontend to hit its provider timeout"),
        ("return to OpenGUI", "return to PortableAI Native Chat"),
        ("strand OpenGUI with Qwen offline", "strand PortableAI Native Chat with Qwen offline"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)

    # Catch remaining prose-only occurrences conservatively. Do not rename files,
    # launchers, or the legacy product name where it is explicitly being discussed.
    text = re.sub(
        r"\bOpenGUI\b(?=\s+(?:renders?|host|conversation|UI|frontend|timeout|tool))",
        "PortableAI Native Chat",
        text,
        flags=re.I,
    )
    return text


def add_policy(text: str) -> str:
    if MARKER in text:
        return text
    block = f"""
============================================================
{MARKER}
NATIVE FRONTEND POLICY
============================================================

PortableAI Native Chat is the PRIMARY local frontend.
Legacy OpenGUI is fallback-only and must not be assumed to be running.

Native Chat directly owns:
- streamed Qwen text + reasoning display
- persistent chat histories and rolling context summaries
- attachments / multimodal image input
- foreground PortableAI tool execution and cancellation
- microphone -> faster-whisper transcription
- generated/downloaded media cards and previews

When a documented Agent\\ai_tools.py or Agent\\web_tools.py route applies, use it
exactly as documented. Do not invent an OpenGUI-specific recovery path.

If Qwen is temporarily stopped by PortableAI's heavy-GPU handoff, allow the
existing host lifecycle code to restore it before continuing the conversation.

A successful tool result may contain preview metadata, but Native Chat can also
render returned local output paths directly. Always preserve the final local path.

"""
    lines = text.splitlines(True)
    # Keep the title at the very top, then insert the policy.
    if lines:
        return lines[0] + block + "".join(lines[1:])
    return block + text


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--backup-dir", default="")
    ns = ap.parse_args()
    root = Path(ns.root).resolve()

    src, current_n = latest_master(root)
    original = src.read_text(encoding="utf-8-sig", errors="replace")

    if MARKER in original:
        print(f"[OK] Native frontend policy already present: {src.name}")
        return 0

    if ns.backup_dir:
        backup_dir = Path(ns.backup_dir).resolve()
        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, backup_dir / src.name)

    new_n = current_n + 1
    suffix = src.suffix.lower() if src.suffix.lower() in (".txt", ".md") else ".txt"
    dst = root / f"PortableAI_Master_Instructions_v{new_n}{suffix}"

    updated = add_policy(frontend_neutralize(original))
    # Update a simple title if it carries the old numeric vNN label.
    updated = re.sub(
        r"^(PORTABLEAI MASTER INSTRUCTIONS\s*[—-]\s*)v\d+\b",
        rf"\g<1>v{new_n}",
        updated,
        count=1,
        flags=re.I | re.M,
    )
    dst.write_text(updated, encoding="utf-8")
    print(f"[OK] Created frontend-neutral master instructions: {dst.name}")
    print(f"     Source preserved: {src.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
