from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def _science_paths() -> tuple[Path, Path]:
    root = _root()
    return root / "Scientific", root / ("Runtime/ScientificPython/packages" if os.name=='nt' else "Runtime/LinuxPackages/science")


_DLL_HANDLES = []


def _activate() -> None:
    science_dir, packages = _science_paths()
    for p in (str(packages), str(science_dir.parent), str(science_dir)):
        if p not in sys.path:
            sys.path.insert(0, p)

    # Windows native wheels can keep companion DLLs in package-specific or .data
    # directories. Keep os.add_dll_directory() handles alive for the lifetime of
    # this process; dropping the returned handle immediately removes that search
    # path again on modern Python.
    if os.name == "nt" and packages.exists() and hasattr(os, "add_dll_directory"):
        candidates = {
            packages,
            packages / "rdkit",
            packages / "openmm",
            packages / "OCP",
            packages / "gmsh",
        }
        try:
            for dll in packages.rglob("*.dll"):
                low = dll.name.lower()
                if low.startswith("gmsh") or "openmm" in low or "rdkit" in str(dll.parent).lower() or "ocp" in str(dll.parent).lower():
                    candidates.add(dll.parent)
        except OSError:
            pass
        seen = {str(getattr(h, "path", "")).lower() for h in _DLL_HANDLES}
        for p in sorted(candidates, key=lambda x: len(str(x))):
            if not p.exists() or str(p).lower() in seen:
                continue
            try:
                h = os.add_dll_directory(str(p))
                _DLL_HANDLES.append(h)
                seen.add(str(p).lower())
            except OSError:
                pass


def _parse_scalar(value: str) -> Any:
    s = value.strip()
    try:
        return json.loads(s)
    except Exception:
        return s


def _load_payload(
    kv: list[str] | None = None,
    json_text: str | None = None,
    file: str | None = None,
) -> dict[str, Any]:
    sources = int(bool(kv)) + int(bool(json_text)) + int(bool(file))
    if sources > 1:
        raise ValueError("Use only one of --set, --json, or --file.")

    if file:
        from media_paths import media_reference
        p = media_reference(_root(), file)
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Science request file must contain one JSON object.")
        return data

    if json_text:
        data = json.loads(json_text)
        if not isinstance(data, dict):
            raise ValueError("--json must decode to one JSON object.")
        return data

    data: dict[str, Any] = {}
    for item in kv or []:
        if "=" not in item:
            raise ValueError(f"Invalid --set value {item!r}; expected KEY=VALUE.")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("Empty key in --set.")
        data[key] = _parse_scalar(value)
    return data


def run_science_request(
    operation: str,
    kv: list[str] | None = None,
    json_text: str | None = None,
    file: str | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    _activate()
    from Scientific.science_core import run_operation

    payload = _load_payload(kv=kv, json_text=json_text, file=file)
    if output_dir:
        payload["output_dir"] = output_dir

    result = run_operation(operation, payload, portableai_root=_root())
    if not isinstance(result, dict):
        result = {"result": result}
    # PORTABLEAI_SCIENCE_FAST_ROUTING_v15_134c
    op_key = str(operation or "").strip().lower()
    result["_portableai"] = {
        "terminal_result": op_key != "status",
        "route_discovery_required": False,
        "next_action": "answer_user" if op_key != "status" else "report_status",
        "response_hint": (
            "Answer directly from this successful deterministic result. Do not run science status/help, "
            "repeat the operation, or perform a second verification tool call unless the user asked for it."
            if op_key != "status" else
            "This is capability inventory only. For a known user task, call the specific science operation directly next time."
        ),
    }
    return {
        "success": True,
        "tool": "science",
        "operation": operation,
        "science_version": "15.130",
        **result,
    }
