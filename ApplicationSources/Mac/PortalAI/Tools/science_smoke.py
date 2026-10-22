from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

VERSION = "15.134c"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000 if os.name == "nt" else 0)


def _parse_json_output(text: str):
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty JSON output")
    try:
        return json.loads(raw)
    except Exception:
        # Allow harmless wrapper text by trying JSON suffixes from the end.
        for i in reversed([i for i, c in enumerate(raw) if c == "{"]):
            try:
                return json.loads(raw[i:])
            except Exception:
                pass
        raise


def _invoke(root: Path, op: str, payload: dict | None = None, timeout: float = 90.0) -> dict:
    py = root / "Runtime" / "BootstrapPython" / "python.exe"
    ai = root / "Agent" / "ai_tools.py"
    args = [str(py), str(ai), "science", op]
    if payload is not None:
        args += ["--json", json.dumps(payload, separators=(",", ":"))]
    cp = subprocess.run(
        args,
        cwd=str(root),
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        creationflags=(CREATE_NO_WINDOW if os.name == "nt" else 0),
    )
    out = (cp.stdout or "").strip()
    err = (cp.stderr or "").strip()
    if cp.returncode != 0:
        raise RuntimeError((out + "\n" + err).strip()[-6000:])
    data = _parse_json_output(out)
    if isinstance(data, dict) and data.get("success") is False:
        raise RuntimeError(str(data.get("error") or data))
    return data


def _row(status: str, label: str, detail: str = "", operation: str | None = None) -> dict:
    return {"status": status, "label": label, "detail": detail, "operation": operation}


def _openmm_probe(root: Path) -> dict:
    # Use the same local-package activation path as normal Science requests.
    agent = str(root / "Agent")
    if agent not in sys.path:
        sys.path.insert(0, agent)
    import scientific_tool_bridge as stb

    stb._activate()
    import openmm as mm
    import openmm.unit as unit

    system = mm.System()
    system.addParticle(39.948)
    integrator = mm.VerletIntegrator(0.001 * unit.picoseconds)
    cpu = mm.Platform.getPlatformByName("CPU")
    ctx = mm.Context(system, integrator, cpu)
    ctx.setPositions([[0, 0, 0]] * unit.nanometer)
    _ = ctx.getState(getEnergy=True).getPotentialEnergy()
    del ctx, integrator
    names = [mm.Platform.getPlatform(i).getName() for i in range(mm.Platform.getNumPlatforms())]
    return {"cpu_context": True, "platforms": names, "cuda_available": "CUDA" in names, "opencl_available": "OpenCL" in names}


def run_suite(root: Path, *, cleanup: bool = True) -> dict:
    root = Path(root).resolve()
    from science_extension_checks import rows as extension_rows
    rows: list[dict] = extension_rows(root)
    work = root / "Agent" / ".runtime" / "science_diagnostics_v15_134c"
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    def test(label, op, payload, check=None, timeout=90):
        try:
            data = _invoke(root, op, payload, timeout)
            ok = True if check is None else bool(check(data))
            rows.append(_row("PASS" if ok else "FAIL", label, ("ok" if ok else "unexpected result") + f" · {op}", op))
            return data
        except Exception as exc:
            rows.append(_row("FAIL", label, f"{type(exc).__name__}: {exc}", op))
            return None

    # science status performs native imports and a functional Gmsh initialize/model.add/finalize probe.
    try:
        status = _invoke(root, "status", None, 120)
        rows.append(_row("PASS", "Science dispatcher + native package inventory", f"science_version={status.get('science_version') or status.get('version')}", "status"))
        packages = status.get("packages") or {}
        for key, label in (
            ("gmsh", "Gmsh native SDK"),
            ("cadquery", "CadQuery/OCP"),
            ("rdkit", "RDKit"),
            ("openmm", "OpenMM import"),
            ("pymunk", "Pymunk"),
        ):
            data = packages.get(key) or {}
            good = bool(data.get("installed")) and data.get("usable") is not False
            rows.append(_row("PASS" if good else "FAIL", f"Science native runtime · {label}", json.dumps(data, sort_keys=True)[:1200], "status"))
        for key, label in (("mafft", "MAFFT optional external"), ("kicad_cli", "KiCad CLI optional external")):
            data = packages.get(key) or {}
            rows.append(_row("PASS" if data.get("installed") else "WARN", label, json.dumps(data, sort_keys=True)[:1000], "status"))
    except Exception as exc:
        rows.append(_row("FAIL", "Science dispatcher + native package inventory", f"{type(exc).__name__}: {exc}", "status"))

    test("Science · units", "units.convert", {"value": 1, "from": "meter", "to": "centimeter"}, lambda d: abs(float(d.get("value", 0)) - 100) < 1e-9)
    test("Science · symbolic math", "math.symbolic", {"expr": "x**2", "action": "differentiate", "var": "x"}, lambda d: "2*x" in str(d.get("result", "")))
    test("Science · statistics", "stats.describe", {"values": [1, 2, 3, 4]}, lambda d: abs(float(d.get("mean", 0)) - 2.5) < 1e-9)
    test("Science · signal FFT", "signal.fft", {"samples": [0, 1, 0, -1, 0, 1, 0, -1], "sample_rate_hz": 8, "top_n": 1}, lambda d: bool(d.get("peaks")))

    cad = test(
        "Science · CAD model",
        "cad.model",
        {"name": "diag_cube", "operations": [{"kind": "box", "size": [1, 1, 1]}], "formats": ["stl"], "output_dir": str(work)},
        lambda d: bool(d.get("files")),
        120,
    )
    if cad and cad.get("files"):
        test("Science · mesh inspection", "mesh.inspect", {"input": cad["files"][0]}, lambda d: int(d.get("vertices", 0)) > 0 and int(d.get("faces", 0)) > 0)
    else:
        rows.append(_row("FAIL", "Science · mesh inspection", "skipped because CAD export failed", "mesh.inspect"))

    test("Science · mechanical", "mechanical.beam", {"length_m": 1, "E_pa": 200000000000, "I_m4": 1e-6, "case": "cantilever_tip", "load_n": 100}, lambda d: float(d.get("tip_deflection_m", 0)) > 0)
    test("Science · electrical", "electrical.dc", {"elements": [{"type": "V", "name": "V1", "n1": "1", "n2": "0", "value": 5}, {"type": "R", "n1": "1", "n2": "0", "value": 1000}]}, lambda d: abs(float((d.get("node_voltages_v") or {}).get("1", 0)) - 5) < 1e-6)
    test("Science · chemistry", "chem.describe", {"smiles": "CCO"}, lambda d: "C2H6O" in str(d.get("formula", "")))
    test("Science · genomics", "genome.translate", {"sequence": "ATGGCC"}, lambda d: str(d.get("protein", "")) == "MA")
    test(
        "Science · SBOL circuit",
        "circuit.sbol",
        {"name": "diag_circuit", "output_dir": str(work), "parts": [{"name": "promoter", "type": "DNA", "sequence": "TTGACA"}, {"name": "gene", "type": "DNA", "sequence": "ATGGCC"}]},
        lambda d: bool(d.get("sbol_file")),
    )

    try:
        opm = _openmm_probe(root)
        rows.append(_row("PASS", "Science · protein/OpenMM CPU engine", f"platforms={opm['platforms']}", "openmm-cpu-context"))
        rows.append(_row("PASS" if opm["cuda_available"] else "WARN", "Science · CUDA platform availability", "CUDA plugin visible; not exercised by routine diagnostics" if opm["cuda_available"] else "CUDA OpenMM platform not visible; CPU Science remains usable", "openmm-cuda-availability"))
        rows.append(_row("PASS" if opm["opencl_available"] else "WARN", "Science · OpenCL platform availability", "OpenCL plugin visible; GPU/driver execution needs the explicit science OpenCL smoke test" if opm["opencl_available"] else "OpenCL plugin absent; CPU science remains usable", "openmm-opencl-availability"))
    except Exception as exc:
        rows.append(_row("FAIL", "Science · protein/OpenMM CPU engine", f"{type(exc).__name__}: {exc}", "openmm-cpu-context"))

    test("Science · physics analytic", "physics.projectile", {"speed_m_s": 10, "angle_deg": 45}, lambda d: float(d.get("range_m", 0)) > 0)
    test("Science · physics rigid body", "physics.rigid2d", {"height_m": 0.5, "duration_s": 0.05, "timestep_s": 0.005}, lambda d: bool(d.get("engine")))

    # Verify dynamic VRAM wiring without intentionally unloading the user's working Qwen session.
    try:
        service_text = (root / "Agent" / "service_manager.py").read_text(encoding="utf-8", errors="ignore")
        ai_text = (root / "Agent" / "ai_tools.py").read_text(encoding="utf-8", errors="ignore")
        ok = all(x in service_text for x in ("science_workload", "acquire_gpu_lease", "qwen_gpu_handoff_begin", "openmm-cuda", "openmm-opencl")) and "science_workload" in ai_text
        rows.append(_row("PASS" if ok else "FAIL", "Science · CUDA/OpenCL handoff path", "structural path present; routine diagnostics do not intentionally unload Qwen" if ok else "required lease/handoff hooks missing", "science-gpu-lifecycle"))
    except Exception as exc:
        rows.append(_row("FAIL", "Science · CUDA/OpenCL handoff path", str(exc), "science-gpu-lifecycle"))

    counts = {s: sum(1 for r in rows if r["status"] == s) for s in ("PASS", "WARN", "FAIL")}
    if cleanup:
        shutil.rmtree(work, ignore_errors=True)
    return {
        "version": VERSION,
        "counts": counts,
        "rows": rows,
        "coverage": {
            "families": ["math/stats/signal", "CAD/mesh", "mechanical", "electrical", "chemistry", "genomics/SBOL", "protein/OpenMM CPU", "physics", "CUDA/OpenCL lifecycle structural"],
            "gpu_execution": "not run by default; avoids evicting a working Qwen session",
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="PortableAI Science Workbench functional smoke suite v15.134c")
    ap.add_argument("--root", required=True)
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args()
    result = run_suite(Path(ns.root))
    if ns.json:
        print(json.dumps(result, indent=2))
    else:
        print("=" * 78)
        print(f"PortableAI v{VERSION} Science Workbench Functional Test")
        print("=" * 78)
        for row in result["rows"]:
            print(f"[{row['status']:<4}] {row['label']}")
            if row.get("detail"):
                print("       " + str(row["detail"]).replace("\n", "\n       "))
        c = result["counts"]
        print("-" * 78)
        print(f"PASS={c['PASS']} WARN={c['WARN']} FAIL={c['FAIL']}")
        print("GPU note: CUDA/OpenCL plugin visibility and lease wiring are checked; routine diagnostics do not evict Qwen or execute GPU minimization. Use Tools/smoke_science_opencl.py for an explicit live OpenCL test.")
    return 1 if result["counts"]["FAIL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
