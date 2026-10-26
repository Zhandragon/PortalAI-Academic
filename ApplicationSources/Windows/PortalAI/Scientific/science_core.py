from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable


VERSION = "15.130"

_agent = str(Path(__file__).resolve().parents[1] / 'Agent')
if _agent not in sys.path:
    sys.path.insert(0, _agent)
from profile_paths import private_path
from media_paths import media_output, media_reference


def _need(module: str, install_name: str | None = None):
    try:
        return __import__(module, fromlist=["*"])
    except Exception as exc:
        raise RuntimeError(
            f"Scientific capability requires {install_name or module!r}. "
            "Run the v15.129 scientific installer or `science status`."
        ) from exc


def _outdir(payload: dict[str, Any], root: Path, domain: str) -> Path:
    if payload.get("output_dir"):
        out = media_output(root, str(payload["output_dir"]))
    else:
        out = private_path(root, 'Outputs/Science') / domain
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    return out


def _write_json(path: Path, data: Any) -> str:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _float(v: Any, name: str) -> float:
    try:
        return float(v)
    except Exception as exc:
        raise ValueError(f"{name} must be numeric, got {v!r}") from exc


def _safe_name(s: str) -> str:
    s = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in s.strip())
    return s[:96] or "result"


# ---------------------------------------------------------------------------
# Status / inventory
# ---------------------------------------------------------------------------

def op_status(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    # Inventory with distribution metadata first. This avoids importing packages
    # such as SKiDL solely for status, which previously emitted misleading KiCad
    # environment warnings even when the scientific toolkit itself was healthy.
    import importlib
    import importlib.metadata as md

    dists = {
        "numpy": "numpy",
        "scipy": "scipy",
        "sympy": "sympy",
        "pint": "pint",
        "matplotlib": "matplotlib",
        "trimesh": "trimesh",
        "cadquery": "cadquery",
        "gmsh": "gmsh",
        "rdkit": "rdkit",
        "biopython": "biopython",
        "sbol3": "sbol3",
        "biotite": "biotite",
        "openmm": "openmm",
        "pymunk": "pymunk",
        "periodictable": "periodictable",
        "skidl": "skidl",
        "ezdxf": "ezdxf",
    }
    status: dict[str, dict[str, Any]] = {}
    for name, dist in dists.items():
        try:
            status[name] = {"installed": True, "version": md.version(dist), "usable": None}
        except md.PackageNotFoundError:
            status[name] = {"installed": False, "version": None, "usable": False}
        except Exception as exc:
            status[name] = {"installed": False, "version": None, "usable": False, "error": str(exc).splitlines()[-1][:240]}

    # Smoke-import only native stacks where metadata alone would hide a broken DLL
    # or ABI. Do not import SKiDL here; it probes KiCad libraries at import time.
    native_checks = {
        "cadquery": "cadquery",
        "rdkit": "rdkit",
        "openmm": "openmm",
        "pymunk": "pymunk",
    }
    for name, module in native_checks.items():
        if not status.get(name, {}).get("installed"):
            continue
        try:
            importlib.import_module(module)
            status[name]["usable"] = True
        except Exception as exc:
            status[name]["usable"] = False
            status[name]["error"] = str(exc).splitlines()[-1][:240]

    if status.get("gmsh", {}).get("installed"):
        try:
            gmsh = importlib.import_module("gmsh")
            gmsh.initialize([])
            try:
                # A tiny API call proves the native SDK loaded, not merely gmsh.py.
                gmsh.model.add("portableai_status_probe")
            finally:
                gmsh.finalize()
            status["gmsh"]["usable"] = True
        except Exception as exc:
            status["gmsh"]["usable"] = False
            status["gmsh"]["error"] = str(exc).splitlines()[-1][:240]

    mafft = _find_mafft(root)
    kicad = _find_kicad(root)
    status["mafft"] = {"installed": bool(mafft), "version": None, "usable": bool(mafft), "path": mafft, "optional": True}
    status["kicad_cli"] = {"installed": bool(kicad), "version": None, "usable": bool(kicad), "path": kicad, "optional": True}

    return {
        "version": VERSION,
        "packages": status,
        "capabilities": sorted(set(OPERATIONS) | set(__import__('Scientific.biology_tool', fromlist=['HELP']).HELP)),
        "optional_external": {
            "mafft": "Required only for genome.msa",
            "kicad_cli": "Required only for electrical.kicad_export",
        },
        "gpu_note": "Core science tools use CPU/RAM. OpenMM defaults explicitly to CPU; requested CUDA/OpenCL runs under the shared GPU lease and chat handoff. No persistent science GPU worker is started.",
    }


# ---------------------------------------------------------------------------
# Units, math, statistics, signal
# ---------------------------------------------------------------------------

def op_units_convert(p: dict[str, Any], root: Path) -> dict[str, Any]:
    pint = _need("pint")
    ureg = pint.UnitRegistry()
    q = _float(p["value"], "value") * ureg(str(p["from"]))
    result = q.to(str(p["to"]))
    return {"value": result.magnitude, "unit": f"{result.units}", "input": f"{q}"}


def op_math_symbolic(p: dict[str, Any], root: Path) -> dict[str, Any]:
    sp = _need("sympy")
    expr_text = str(p["expr"])
    action = str(p.get("action", "simplify")).lower()
    var_name = str(p.get("var", "x"))
    var = sp.Symbol(var_name)
    locals_ = {
        var_name: var,
        "pi": sp.pi, "E": sp.E,
        "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
        "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
        "exp": sp.exp, "log": sp.log, "sqrt": sp.sqrt,
        "Abs": sp.Abs,
    }
    expr = sp.sympify(expr_text, locals=locals_)

    if action == "simplify":
        out = sp.simplify(expr)
    elif action in ("differentiate", "diff", "derivative"):
        out = sp.diff(expr, var, int(p.get("order", 1)))
    elif action in ("integrate", "integral"):
        if "a" in p and "b" in p:
            out = sp.integrate(expr, (var, sp.sympify(p["a"]), sp.sympify(p["b"])))
        else:
            out = sp.integrate(expr, var)
    elif action == "solve":
        out = sp.solve(sp.Eq(expr, sp.sympify(p.get("equals", 0))), var)
    elif action == "series":
        out = sp.series(expr, var, sp.sympify(p.get("about", 0)), int(p.get("order", 6)))
    else:
        raise ValueError(f"Unsupported symbolic action: {action}")
    return {"expression": expr_text, "action": action, "result": str(out), "latex": sp.latex(out)}


def op_stats_describe(p: dict[str, Any], root: Path) -> dict[str, Any]:
    np = _need("numpy")
    vals = np.asarray(p["values"], dtype=float)
    if vals.size == 0:
        raise ValueError("values cannot be empty")
    q = np.percentile(vals, [25, 50, 75])
    return {
        "n": int(vals.size),
        "mean": float(np.mean(vals)),
        "std_sample": float(np.std(vals, ddof=1)) if vals.size > 1 else None,
        "min": float(np.min(vals)),
        "q1": float(q[0]),
        "median": float(q[1]),
        "q3": float(q[2]),
        "max": float(np.max(vals)),
    }


def op_signal_fft(p: dict[str, Any], root: Path) -> dict[str, Any]:
    np = _need("numpy")
    samples = np.asarray(p["samples"], dtype=float)
    fs = _float(p["sample_rate_hz"], "sample_rate_hz")
    if samples.ndim != 1 or samples.size < 2:
        raise ValueError("samples must be a one-dimensional array with >=2 points")
    y = np.fft.rfft(samples - np.mean(samples))
    f = np.fft.rfftfreq(samples.size, 1.0 / fs)
    mag = np.abs(y) * 2.0 / samples.size
    order = np.argsort(mag[1:])[::-1][: int(p.get("top_n", 8))] + 1
    peaks = [{"frequency_hz": float(f[i]), "amplitude": float(mag[i])} for i in order]
    return {"n": int(samples.size), "sample_rate_hz": fs, "peaks": peaks}


# ---------------------------------------------------------------------------
# CAD / mesh / blueprinting
# ---------------------------------------------------------------------------

def _cq_primitive(cq, item: dict[str, Any]):
    kind = str(item.get("kind", "box")).lower()
    at = tuple(float(x) for x in item.get("at", [0, 0, 0]))
    if kind == "box":
        size = item.get("size")
        if not size or len(size) != 3:
            raise ValueError("box requires size=[x,y,z]")
        shape = cq.Workplane("XY").box(*map(float, size), centered=(True, True, False))
    elif kind == "cylinder":
        shape = cq.Workplane("XY").circle(_float(item["radius"], "radius")).extrude(_float(item["height"], "height"))
    elif kind == "sphere":
        shape = cq.Workplane("XY").sphere(_float(item["radius"], "radius"))
    elif kind == "tube":
        ro = _float(item["outer_radius"], "outer_radius")
        ri = _float(item["inner_radius"], "inner_radius")
        h = _float(item["height"], "height")
        shape = cq.Workplane("XY").circle(ro).circle(ri).extrude(h)
    elif kind == "plate":
        w, d = map(float, item["size"][:2])
        t = _float(item["thickness"], "thickness")
        shape = cq.Workplane("XY").box(w, d, t, centered=(True, True, False))
        for hole in item.get("holes", []):
            x, y = map(float, hole["at"][:2])
            dia = _float(hole["diameter"], "diameter")
            shape = shape.faces(">Z").workplane().pushPoints([(x, y)]).hole(dia)
    else:
        raise ValueError(f"Unsupported CAD primitive kind: {kind}")
    return shape.translate(at)


def op_cad_model(p: dict[str, Any], root: Path) -> dict[str, Any]:
    cq = _need("cadquery")
    out = _outdir(p, root, "cad")
    name = _safe_name(str(p.get("name", "model")))
    operations = p.get("operations") or []
    if not operations:
        raise ValueError("operations cannot be empty")

    model = None
    for item in operations:
        shape = _cq_primitive(cq, item)
        mode = str(item.get("mode", "add")).lower()
        if model is None:
            if mode == "cut":
                raise ValueError("First CAD operation cannot be cut.")
            model = shape
        elif mode in ("add", "union"):
            model = model.union(shape)
        elif mode == "cut":
            model = model.cut(shape)
        elif mode in ("intersect", "intersection"):
            model = model.intersect(shape)
        else:
            raise ValueError(f"Unsupported CAD boolean mode: {mode}")

    formats = [str(x).lower() for x in p.get("formats", ["step", "stl"])]
    outputs = []
    if "step" in formats or "stp" in formats:
        path = out / f"{name}.step"
        cq.exporters.export(model, str(path))
        outputs.append(str(path))
    if "stl" in formats:
        path = out / f"{name}.stl"
        cq.exporters.export(model, str(path))
        outputs.append(str(path))

    bb = model.val().BoundingBox()
    info = {
        "name": name,
        "bounding_box": {"x": bb.xlen, "y": bb.ylen, "z": bb.zlen},
        "files": outputs,
    }
    _write_json(out / f"{name}.json", info)
    return info


def op_mesh_inspect(p: dict[str, Any], root: Path) -> dict[str, Any]:
    trimesh = _need("trimesh")
    path = media_reference(root, str(p["input"]))
    mesh = trimesh.load_mesh(path, force="mesh")
    return {
        "input": str(path),
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "watertight": bool(mesh.is_watertight),
        "volume": float(mesh.volume) if mesh.is_volume else None,
        "surface_area": float(mesh.area),
        "bounds": mesh.bounds.tolist(),
        "center_mass": mesh.center_mass.tolist() if mesh.is_volume else mesh.centroid.tolist(),
    }


def _svg_dim_line(x1, y1, x2, y2, label, horiz=True):
    if horiz:
        tx, ty = (x1+x2)/2, y1-8
    else:
        tx, ty = x1-10, (y1+y2)/2
    return f'''
    <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="black" stroke-width="1"/>
    <line x1="{x1}" y1="{y1-4}" x2="{x1}" y2="{y1+4}" stroke="black"/>
    <line x1="{x2}" y1="{y2-4}" x2="{x2}" y2="{y2+4}" stroke="black"/>
    <text x="{tx}" y="{ty}" font-size="10" text-anchor="middle">{label}</text>'''


def op_cad_blueprint(p: dict[str, Any], root: Path) -> dict[str, Any]:
    out = _outdir(p, root, "blueprints")
    name = _safe_name(str(p.get("name", "blueprint")))
    w = _float(p["width"], "width")
    d = _float(p["depth"], "depth")
    h = _float(p["height"], "height")
    units = str(p.get("units", "mm"))
    maxdim = max(w, d, h)
    scale = 180.0 / maxdim if maxdim else 1.0

    def rect(x, y, a, b, title):
        return (
            f'<rect x="{x}" y="{y}" width="{a*scale}" height="{b*scale}" fill="none" stroke="black" stroke-width="1.5"/>'
            f'<text x="{x}" y="{y-12}" font-size="13">{title}</text>'
        )

    fw, fh = w*scale, h*scale
    tw, td = w*scale, d*scale
    rw, rh = d*scale, h*scale
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="900" height="650" viewBox="0 0 900 650">
    <rect width="100%" height="100%" fill="white"/>
    <text x="30" y="32" font-size="20" font-weight="bold">{name}</text>
    <text x="30" y="52" font-size="11">Orthographic basic blueprint; dimensions in {units}</text>
    {rect(70,120,w,h,"FRONT")}
    {_svg_dim_line(70, 120+fh+28, 70+fw, 120+fh+28, f"{w:g} {units}")}
    {rect(380,120,d,h,"RIGHT")}
    {_svg_dim_line(380, 120+rh+28, 380+rw, 120+rh+28, f"{d:g} {units}")}
    {rect(70,400,w,d,"TOP")}
    {_svg_dim_line(70, 400+td+28, 70+tw, 400+td+28, f"{w:g} {units}")}
    <text x="700" y="600" font-size="10">PortableAI Scientific Toolkit v{VERSION}</text>
    </svg>'''
    path = out / f"{name}.svg"
    path.write_text(svg, encoding="utf-8")
    return {"file": str(path), "dimensions": {"width": w, "depth": d, "height": h, "units": units}}


# ---------------------------------------------------------------------------
# Mechanical engineering / simple FEM
# ---------------------------------------------------------------------------

def op_mechanical_beam(p: dict[str, Any], root: Path) -> dict[str, Any]:
    L = _float(p["length_m"], "length_m")
    E = _float(p["E_pa"], "E_pa")
    I = _float(p["I_m4"], "I_m4")
    case = str(p.get("case", "cantilever_tip")).lower()

    if case == "cantilever_tip":
        P = _float(p["load_n"], "load_n")
        return {"case": case, "max_moment_nm": P*L, "tip_deflection_m": P*L**3/(3*E*I)}
    if case == "simply_supported_center":
        P = _float(p["load_n"], "load_n")
        return {"case": case, "max_moment_nm": P*L/4, "midspan_deflection_m": P*L**3/(48*E*I)}
    if case == "simply_supported_udl":
        w = _float(p["load_n_per_m"], "load_n_per_m")
        return {"case": case, "max_moment_nm": w*L**2/8, "midspan_deflection_m": 5*w*L**4/(384*E*I)}
    raise ValueError("case must be cantilever_tip, simply_supported_center, or simply_supported_udl")


def op_mechanical_truss2d(p: dict[str, Any], root: Path) -> dict[str, Any]:
    np = _need("numpy")
    out = _outdir(p, root, "mechanical")
    name = _safe_name(str(p.get("name", "truss2d")))
    nodes = {str(k): np.array(v, dtype=float) for k, v in p["nodes"].items()}
    ids = list(nodes)
    idx = {n: i for i, n in enumerate(ids)}
    ndof = 2 * len(ids)
    K = np.zeros((ndof, ndof), dtype=float)

    elems = []
    for e in p["elements"]:
        ni, nj = str(e["i"]), str(e["j"])
        xi, xj = nodes[ni], nodes[nj]
        dx = xj - xi
        L = float(np.linalg.norm(dx))
        if L <= 0:
            raise ValueError("Zero-length truss element")
        c, s = dx[0]/L, dx[1]/L
        E, A = float(e["E"]), float(e["A"])
        k = E*A/L * np.array([
            [c*c, c*s, -c*c, -c*s],
            [c*s, s*s, -c*s, -s*s],
            [-c*c, -c*s, c*c, c*s],
            [-c*s, -s*s, c*s, s*s],
        ])
        dof = [2*idx[ni], 2*idx[ni]+1, 2*idx[nj], 2*idx[nj]+1]
        K[np.ix_(dof, dof)] += k
        elems.append((e, L, c, s, dof))

    F = np.zeros(ndof)
    for n, load in (p.get("loads") or {}).items():
        i = idx[str(n)]
        F[2*i:2*i+2] += np.asarray(load, dtype=float)

    fixed = []
    for n, cons in (p.get("constraints") or {}).items():
        i = idx[str(n)]
        if bool(cons[0]): fixed.append(2*i)
        if bool(cons[1]): fixed.append(2*i+1)
    free = [i for i in range(ndof) if i not in fixed]
    if not fixed:
        raise ValueError("At least one constraint is required.")

    U = np.zeros(ndof)
    try:
        U[free] = np.linalg.solve(K[np.ix_(free, free)], F[free])
    except np.linalg.LinAlgError as exc:
        raise ValueError("Truss stiffness matrix is singular; check supports/connectivity.") from exc
    R = K @ U - F

    elem_results = []
    for e, L, c, s, dof in elems:
        u = U[dof]
        ext = np.array([-c, -s, c, s]) @ u
        force = float(e["E"]) * float(e["A"]) / L * ext
        stress = force / float(e["A"])
        elem_results.append({
            "i": str(e["i"]), "j": str(e["j"]), "length": L,
            "axial_force": float(force), "stress": float(stress)
        })

    displacements = {n: [float(U[2*i]), float(U[2*i+1])] for n, i in idx.items()}
    reactions = {n: [float(R[2*i]), float(R[2*i+1])] for n, i in idx.items() if 2*i in fixed or 2*i+1 in fixed}
    result = {"name": name, "displacements": displacements, "reactions": reactions, "elements": elem_results}
    path = out / f"{name}_results.json"
    _write_json(path, result)

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 5))
        for e, *_ in elems:
            a, b = nodes[str(e["i"])], nodes[str(e["j"])]
            ax.plot([a[0], b[0]], [a[1], b[1]], "-o")
        mag = float(p.get("deformation_scale", 1.0))
        deformed = {n: nodes[n] + mag*np.array(displacements[n]) for n in ids}
        for e, *_ in elems:
            a, b = deformed[str(e["i"])], deformed[str(e["j"])]
            ax.plot([a[0], b[0]], [a[1], b[1]], "--")
        ax.set_aspect("equal", adjustable="box")
        ax.set_title(f"{name}: undeformed / deformed x{mag:g}")
        ax.set_xlabel("x"); ax.set_ylabel("y"); ax.grid(True, alpha=0.25)
        png = out / f"{name}.png"
        fig.tight_layout(); fig.savefig(png, dpi=160); plt.close(fig)
        result["preview"] = str(png)
    except Exception as exc:
        result["preview_warning"] = str(exc)
    result["file"] = str(path)
    return result


# ---------------------------------------------------------------------------
# Electrical engineering
# ---------------------------------------------------------------------------

def op_electrical_dc(p: dict[str, Any], root: Path) -> dict[str, Any]:
    np = _need("numpy")
    elements = p["elements"]
    node_names = sorted({str(x) for e in elements for x in (e.get("n1", "0"), e.get("n2", "0")) if str(x) != "0"})
    ni = {n: i for i, n in enumerate(node_names)}
    vsrcs = [e for e in elements if str(e["type"]).upper() == "V"]
    N, M = len(node_names), len(vsrcs)
    A = np.zeros((N+M, N+M), float)
    z = np.zeros(N+M, float)
    vmap = {id(e): j for j, e in enumerate(vsrcs)}

    def nidx(n):
        return ni.get(str(n)) if str(n) != "0" else None

    for e in elements:
        typ = str(e["type"]).upper()
        a, b = nidx(e.get("n1", "0")), nidx(e.get("n2", "0"))
        if typ == "R":
            r = _float(e["value"], "resistance")
            if r <= 0: raise ValueError("Resistance must be >0")
            g = 1.0/r
            if a is not None: A[a,a] += g
            if b is not None: A[b,b] += g
            if a is not None and b is not None:
                A[a,b] -= g; A[b,a] -= g
        elif typ == "I":
            cur = _float(e["value"], "current")
            if a is not None: z[a] -= cur
            if b is not None: z[b] += cur
        elif typ == "V":
            j = N + vmap[id(e)]
            if a is not None: A[a,j] += 1; A[j,a] += 1
            if b is not None: A[b,j] -= 1; A[j,b] -= 1
            z[j] = _float(e["value"], "voltage")
        else:
            raise ValueError(f"Unsupported DC element type {typ}; use R, I, or V.")
    try:
        x = np.linalg.solve(A, z)
    except np.linalg.LinAlgError as exc:
        raise ValueError("Circuit matrix is singular; check for floating nodes or contradictory ideal sources.") from exc

    voltages = {"0": 0.0, **{n: float(x[i]) for n, i in ni.items()}}
    source_currents = {}
    for e in vsrcs:
        name = str(e.get("name") or f"V{vmap[id(e)]+1}")
        source_currents[name] = float(x[N+vmap[id(e)]])
    return {"node_voltages_v": voltages, "voltage_source_currents_a": source_currents}


def op_electrical_rc(p: dict[str, Any], root: Path) -> dict[str, Any]:
    R = _float(p["resistance_ohm"], "resistance_ohm")
    C = _float(p["capacitance_f"], "capacitance_f")
    tau = R*C
    return {"time_constant_s": tau, "cutoff_hz": 1/(2*math.pi*tau) if tau > 0 else math.inf}


def _find_kicad(root: Path) -> str | None:
    candidates = ([root / 'Runtime/KiCad/linux-x64/bin/kicad-cli'] if os.name != 'nt' else [
        root / "Tools" / "KiCad" / "bin" / "kicad-cli.exe",
        root / "Tools" / "KiCad" / "kicad-cli.exe",
    ])
    for c in candidates:
        if c.exists(): return str(c)
    return shutil.which("kicad-cli")


def op_electrical_kicad_export(p: dict[str, Any], root: Path) -> dict[str, Any]:
    exe = _find_kicad(root)
    if not exe:
        raise RuntimeError("kicad-cli not found. Put a portable KiCad build under Tools\\KiCad or install it separately.")
    inp = media_reference(root, str(p["input"]))
    kind = str(p.get("kind", "schematic-svg"))
    out = _outdir(p, root, "electrical")
    if kind == "schematic-svg":
        cmd = [exe, "sch", "export", "svg", "-o", str(out), str(inp)]
    elif kind == "bom":
        out_file = out / (inp.stem + "_bom.csv")
        cmd = [exe, "sch", "export", "bom", "-o", str(out_file), str(inp)]
    elif kind == "pcb-step":
        out_file = out / (inp.stem + ".step")
        cmd = [exe, "pcb", "export", "step", "-o", str(out_file), str(inp)]
    else:
        raise ValueError("kind must be schematic-svg, bom, or pcb-step")
    if os.name == 'nt':
        from kicad_windows import command_environment
        command, env = command_environment(root)
        cmd = [*command, *cmd[1:]]
        cp = subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True,
                            errors='replace', timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        from linux_owned_run import run
        from runtime_policy import portable_env
        cp = run(cmd, cwd=root, env=portable_env(root), timeout=300, memory_bytes=2*1024**3)
    if cp.returncode:
        raise RuntimeError((cp.stderr or cp.stdout or "kicad-cli failed")[-4000:])
    return {"command": cmd, "stdout": cp.stdout[-4000:], "output_dir": str(out)}


# ---------------------------------------------------------------------------
# Chemistry
# ---------------------------------------------------------------------------

def _rdmol(smiles: str):
    Chem = _need("rdkit.Chem", "rdkit")
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise ValueError("RDKit could not parse the SMILES string.")
    return Chem, mol


def op_chem_describe(p: dict[str, Any], root: Path) -> dict[str, Any]:
    Chem, mol = _rdmol(str(p["smiles"]))
    Descriptors = _need("rdkit.Chem.Descriptors", "rdkit")
    Crippen = _need("rdkit.Chem.Crippen", "rdkit")
    Lipinski = _need("rdkit.Chem.Lipinski", "rdkit")
    rdMolDescriptors = _need("rdkit.Chem.rdMolDescriptors", "rdkit")
    return {
        "canonical_smiles": Chem.MolToSmiles(mol, canonical=True),
        "formula": rdMolDescriptors.CalcMolFormula(mol),
        "molecular_weight": float(Descriptors.MolWt(mol)),
        "logp": float(Crippen.MolLogP(mol)),
        "hbond_donors": int(Lipinski.NumHDonors(mol)),
        "hbond_acceptors": int(Lipinski.NumHAcceptors(mol)),
        "rotatable_bonds": int(Lipinski.NumRotatableBonds(mol)),
        "tpsa": float(rdMolDescriptors.CalcTPSA(mol)),
    }


def op_chem_render(p: dict[str, Any], root: Path) -> dict[str, Any]:
    Chem, mol = _rdmol(str(p["smiles"]))
    Draw = _need("rdkit.Chem.Draw", "rdkit")
    out = _outdir(p, root, "chemistry")
    name = _safe_name(str(p.get("name", "molecule")))
    path = out / f"{name}.svg"
    drawer = Draw.MolDraw2DSVG(int(p.get("width", 800)), int(p.get("height", 500)))
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    path.write_text(drawer.GetDrawingText(), encoding="utf-8")
    return {"file": str(path), **op_chem_describe(p, root)}


def op_chem_conformer(p: dict[str, Any], root: Path) -> dict[str, Any]:
    Chem, mol = _rdmol(str(p["smiles"]))
    AllChem = _need("rdkit.Chem.AllChem", "rdkit")
    out = _outdir(p, root, "chemistry")
    name = _safe_name(str(p.get("name", "molecule_3d")))
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = int(p.get("seed", 0xC0FFEE))
    if AllChem.EmbedMolecule(mol, params) != 0:
        raise RuntimeError("RDKit conformer embedding failed.")
    if bool(p.get("minimize", True)):
        try:
            AllChem.MMFFOptimizeMolecule(mol, maxIters=int(p.get("max_iters", 500)))
        except Exception:
            AllChem.UFFOptimizeMolecule(mol, maxIters=int(p.get("max_iters", 500)))
    path = out / f"{name}.sdf"
    w = Chem.SDWriter(str(path)); w.write(mol); w.close()
    return {"file": str(path), "atoms_with_h": int(mol.GetNumAtoms())}


# ---------------------------------------------------------------------------
# Genomics / proteins / synthetic biology
# ---------------------------------------------------------------------------

def _clean_seq(seq: Any) -> str:
    return "".join(str(seq).split()).upper()


def op_genome_analyze(p: dict[str, Any], root: Path) -> dict[str, Any]:
    seq = _clean_seq(p["sequence"])
    if not seq:
        raise ValueError("sequence is empty")
    alphabet = set(seq)
    dna = alphabet <= set("ACGTN")
    result = {"length": len(seq), "alphabet": "".join(sorted(alphabet)), "dna_like": dna}
    if dna:
        denom = max(1, sum(seq.count(x) for x in "ACGT"))
        gc = (seq.count("G") + seq.count("C")) / denom
        result["gc_fraction_acgt_only"] = gc
        result["gc_percent_acgt_only"] = 100*gc
        result["reverse_complement"] = str(_need("Bio.Seq", "biopython").Seq(seq).reverse_complement())
    return result


def op_genome_translate(p: dict[str, Any], root: Path) -> dict[str, Any]:
    Seq = _need("Bio.Seq", "biopython").Seq
    seq = Seq(_clean_seq(p["sequence"]))
    protein = seq.translate(
        table=int(p.get("table", 1)),
        to_stop=bool(p.get("to_stop", False)),
        cds=bool(p.get("cds", False)),
    )
    return {"protein": str(protein), "aa_length": len(protein)}


def op_genome_align(p: dict[str, Any], root: Path) -> dict[str, Any]:
    # PORTABLEAI_GENOME_ALIGN_STRUCTURED_v15_134c
    PairwiseAligner = _need("Bio.Align", "biopython").PairwiseAligner
    a, b = _clean_seq(p["seq_a"]), _clean_seq(p["seq_b"])
    aligner = PairwiseAligner()
    aligner.mode = str(p.get("mode", "global"))
    aligner.match_score = float(p.get("match", 2))
    aligner.mismatch_score = float(p.get("mismatch", -1))
    aligner.open_gap_score = float(p.get("gap_open", -5))
    aligner.extend_gap_score = float(p.get("gap_extend", -0.5))
    best = aligner.align(a, b)[0]
    raw = str(best)
    aa, bb, mm = [], [], []
    for line in raw.splitlines():
        parts = line.strip().split()
        if len(parts) >= 3 and parts[0] == "target":
            aa.append(parts[2])
        elif len(parts) >= 3 and parts[0] == "query":
            bb.append(parts[2])
        elif len(parts) >= 2:
            token = parts[1]
            if token and set(token) <= set("|.-"):
                mm.append(token)
    aligned_a, aligned_b, match_line = "".join(aa), "".join(bb), "".join(mm)
    columns = max(len(aligned_a), len(aligned_b), len(match_line))
    matches = sum(1 for c in match_line if c == "|")
    mismatches = sum(1 for c in match_line if c == ".")
    gap_columns = sum(1 for x, y in zip(aligned_a, aligned_b) if x == "-" or y == "-") if aligned_a and aligned_b else 0
    compared_no_gap = matches + mismatches
    identity_no_gap = (100.0 * matches / compared_no_gap) if compared_no_gap else None
    identity_all = (100.0 * matches / columns) if columns else None
    return {
        "score": float(best.score),
        "alignment": raw,
        "aligned_seq_a": aligned_a or None,
        "aligned_seq_b": aligned_b or None,
        "match_line": match_line or None,
        "aligned_columns": columns,
        "matches": matches,
        "mismatches": mismatches,
        "gap_columns": gap_columns,
        "identity_percent_aligned": identity_all,
        "identity_percent_no_gap": identity_no_gap,
        "seq_a_length": len(a),
        "seq_b_length": len(b),
        "summary": f"{matches} matches, {mismatches} mismatches, {gap_columns} gap columns; {identity_all:.2f}% identity across aligned columns" if identity_all is not None else "alignment completed",
    }

def _find_mafft(root: Path) -> str | None:
    candidates = ([root / 'Runtime/MAFFT/linux-x64/mafft'] if os.name != 'nt' else [
        root / "Scientific" / "External" / "MAFFT" / "mafft.bat",
        root / "Tools" / "MAFFT" / "mafft.bat",
    ])
    for c in candidates:
        if c.exists(): return str(c)
    return shutil.which("mafft") or (shutil.which("mafft.bat") if os.name=='nt' else None)


def op_genome_msa(p: dict[str, Any], root: Path) -> dict[str, Any]:
    mafft = _find_mafft(root)
    if not mafft:
        raise RuntimeError("MAFFT is not installed for this operating system; the matching portable payload is required.")
    seqs = p["sequences"]
    out = _outdir(p, root, "genomics")
    name = _safe_name(str(p.get("name", "msa")))
    inp = out / f"{name}_input.fasta"
    lines = []
    iterable = seqs.items() if isinstance(seqs, dict) else [(f"seq{i+1}", s) for i, s in enumerate(seqs)]
    for label, seq in iterable:
        lines += [f">{_safe_name(str(label))}", _clean_seq(seq)]
    inp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    outfa = out / f"{name}.fasta"

    # MAFFT writes aligned FASTA to stdout; it does not use a generic --out flag.
    # Build one quoted command line for cmd.exe so portable .bat launchers and paths
    # containing spaces behave consistently on Windows.
    argv = [
        mafft, "--auto", "--thread", str(p.get("threads", -1)), str(inp)
    ]
    cmd = ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(argv)] if os.name=='nt' else argv
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=int(p.get("timeout", 1800)))
    if cp.returncode:
        raise RuntimeError((cp.stderr or cp.stdout or "MAFFT failed")[-4000:])
    if not cp.stdout.strip():
        raise RuntimeError("MAFFT returned success but produced no alignment on stdout.")
    outfa.write_text(cp.stdout, encoding="utf-8")
    return {"file": str(outfa), "input": str(inp), "stderr_tail": cp.stderr[-2000:]}


def op_circuit_sbol(p: dict[str, Any], root: Path) -> dict[str, Any]:
    sbol3 = _need("sbol3")
    out = _outdir(p, root, "genetic_circuits")
    name = _safe_name(str(p.get("name", "genetic_circuit")))
    namespace = str(p.get("namespace", "https://portableai.local/sbol/"))
    sbol3.set_namespace(namespace)
    doc = sbol3.Document()

    components = []
    for part in p.get("parts", []):
        display = _safe_name(str(part["name"]))
        typ = str(part.get("type", "DNA")).upper()
        type_uri = sbol3.SBO_DNA if typ == "DNA" else sbol3.SBO_PROTEIN if typ == "PROTEIN" else sbol3.SBO_DNA
        c = sbol3.Component(display, type_uri)
        if part.get("description"):
            c.description = str(part["description"])
        seq = _clean_seq(part.get("sequence", ""))
        if seq:
            enc = sbol3.IUPAC_DNA_ENCODING if typ == "DNA" else sbol3.IUPAC_PROTEIN_ENCODING
            s = sbol3.Sequence(display + "_seq", elements=seq, encoding=enc)
            doc.add(s)
            c.sequences = [s.identity]
        doc.add(c)
        components.append(c)

    path = out / f"{name}.nt"
    doc.write(str(path), sbol3.SORTED_NTRIPLES)

    svg = out / f"{name}.svg"
    x, y, boxw, boxh = 40, 90, 150, 55
    body = [f'<text x="30" y="35" font-size="20" font-weight="bold">{name}</text>']
    for i, part in enumerate(p.get("parts", [])):
        px = x + i*(boxw+35)
        body.append(f'<rect x="{px}" y="{y}" width="{boxw}" height="{boxh}" rx="8" fill="none" stroke="black" stroke-width="1.5"/>')
        body.append(f'<text x="{px+boxw/2}" y="{y+23}" font-size="12" text-anchor="middle">{part["name"]}</text>')
        body.append(f'<text x="{px+boxw/2}" y="{y+42}" font-size="10" text-anchor="middle">{part.get("role", part.get("type","DNA"))}</text>')
        if i:
            body.append(f'<line x1="{px-35}" y1="{y+boxh/2}" x2="{px}" y2="{y+boxh/2}" stroke="black" marker-end="url(#arrow)"/>')
    width = max(500, x + len(p.get("parts", []))*(boxw+35) + 30)
    svg.write_text(f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="220">
    <defs><marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="black"/></marker></defs>
    <rect width="100%" height="100%" fill="white"/>{''.join(body)}</svg>''', encoding="utf-8")
    return {"sbol_file": str(path), "diagram": str(svg), "part_count": len(components)}


def op_protein_inspect(p: dict[str, Any], root: Path) -> dict[str, Any]:
    PDBParser = _need("Bio.PDB", "biopython").PDBParser
    path = media_reference(root, str(p["input"]))
    structure = PDBParser(QUIET=True).get_structure("protein", str(path))
    chains, atom_count, residues = {}, 0, 0
    for model in structure:
        for chain in model:
            count = 0
            for res in chain:
                if res.id[0] == " ":
                    count += 1
                    atom_count += len(res)
            chains[chain.id] = count
            residues += count
        break
    return {"input": str(path), "chains": chains, "residues": residues, "atoms_standard_residues": atom_count}


def op_protein_render(p: dict[str, Any], root: Path) -> dict[str, Any]:
    PDBParser = _need("Bio.PDB", "biopython").PDBParser
    path = media_reference(root, str(p["input"]))
    out = _outdir(p, root, "proteins")
    name = _safe_name(str(p.get("name", path.stem)))
    structure = PDBParser(QUIET=True).get_structure("protein", str(path))
    coords = []
    for model in structure:
        for chain in model:
            for res in chain:
                if "CA" in res:
                    coords.append(res["CA"].coord)
        break
    if not coords:
        raise ValueError("No C-alpha atoms found.")
    np = _need("numpy")
    xyz = np.asarray(coords)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(7, 6))
    ax = fig.add_subplot(111, projection="3d")
    ax.plot(xyz[:,0], xyz[:,1], xyz[:,2], linewidth=1)
    ax.scatter(xyz[:,0], xyz[:,1], xyz[:,2], s=5)
    ax.set_title(name + " Cα backbone")
    ax.set_xlabel("Å"); ax.set_ylabel("Å"); ax.set_zlabel("Å")
    png = out / f"{name}.png"
    fig.tight_layout(); fig.savefig(png, dpi=180); plt.close(fig)
    return {"file": str(png), "ca_atoms": int(len(coords))}


def _openmm_platform(p, mm):
    # OpenMM's unconstrained auto selection can choose OpenCL and bypass the
    # portable GPU lease. Auto in PortalAI deliberately means CPU science.
    name = str(p.get("platform", p.get("device", "auto"))).strip().lower()
    names = {"auto": "CPU", "cpu": "CPU", "reference": "Reference", "cuda": "CUDA", "opencl": "OpenCL"}
    if name not in names: raise ValueError("OpenMM platform must be auto, cpu, reference, cuda or opencl")
    platform = mm.Platform.getPlatformByName(names[name])
    properties = {}
    if name in ("cuda", "opencl"):
        index = p.get("device_index", 0)
        if isinstance(index, bool) or not str(index).isdigit(): raise ValueError("device_index must select one non-negative GPU index")
        properties["DeviceIndex"] = str(int(index))
        precision = str(p.get("precision", "mixed")).lower()
        if precision not in ("single", "mixed", "double"): raise ValueError("Unknown OpenMM precision")
        properties["Precision"] = precision
    return platform, properties


def op_protein_minimize(p: dict[str, Any], root: Path) -> dict[str, Any]:
    app = _need("openmm.app", "openmm")
    mm = _need("openmm")
    unit = _need("openmm.unit", "openmm")
    platform, properties = _openmm_platform(p, mm)
    path = media_reference(root, str(p["input"]))
    out = _outdir(p, root, "proteins")
    name = _safe_name(str(p.get("name", path.stem + "_minimized")))

    pdb = app.PDBFile(str(path))
    ff = app.ForceField("amber14-all.xml")
    modeller = app.Modeller(pdb.topology, pdb.positions)
    modeller.addHydrogens(ff, pH=float(p.get("pH", 7.0)), platform=mm.Platform.getPlatformByName("CPU"))
    system = ff.createSystem(modeller.topology, nonbondedMethod=app.NoCutoff, constraints=app.HBonds)
    integrator = mm.LangevinMiddleIntegrator(300*unit.kelvin, 1/unit.picosecond, 0.004*unit.picoseconds)
    sim = app.Simulation(modeller.topology, system, integrator, platform, properties)
    sim.context.setPositions(modeller.positions)
    initial = sim.context.getState(getEnergy=True).getPotentialEnergy()
    sim.minimizeEnergy(maxIterations=int(p.get("max_iterations", 1000)))
    state = sim.context.getState(getEnergy=True, getPositions=True)
    final = state.getPotentialEnergy()
    outp = out / f"{name}.pdb"
    with outp.open("w", encoding="utf-8") as fh:
        app.PDBFile.writeFile(modeller.topology, state.getPositions(), fh)
    return {
        "file": str(outp),
        "initial_potential_energy_kj_mol": float(initial.value_in_unit(unit.kilojoule_per_mole)),
        "final_potential_energy_kj_mol": float(final.value_in_unit(unit.kilojoule_per_mole)),
        "platform": sim.context.getPlatform().getName(),
        "note": "Energy minimization/relaxation, not de novo fold prediction.",
    }


# ---------------------------------------------------------------------------
# Physics
# ---------------------------------------------------------------------------

def op_physics_projectile(p: dict[str, Any], root: Path) -> dict[str, Any]:
    v = _float(p["speed_m_s"], "speed_m_s")
    angle = math.radians(_float(p["angle_deg"], "angle_deg"))
    y0 = float(p.get("height_m", 0))
    g = float(p.get("g_m_s2", 9.80665))
    vx, vy = v*math.cos(angle), v*math.sin(angle)
    disc = vy*vy + 2*g*y0
    t = (vy + math.sqrt(max(0.0, disc))) / g
    return {"flight_time_s": t, "range_m": vx*t, "max_height_m": y0 + max(0.0, vy)**2/(2*g), "vx_m_s": vx, "vy0_m_s": vy}


def op_physics_spring_mass(p: dict[str, Any], root: Path) -> dict[str, Any]:
    np = _need("numpy")
    integrate = _need("scipy.integrate", "scipy")
    m = _float(p["mass_kg"], "mass_kg")
    k = _float(p["k_n_m"], "k_n_m")
    c = float(p.get("damping_n_s_m", 0))
    x0 = float(p.get("x0_m", 0.1))
    v0 = float(p.get("v0_m_s", 0))
    T = float(p.get("duration_s", 10))
    n = int(p.get("samples", 500))
    ts = np.linspace(0, T, n)

    def f(t, y):
        x, v = y
        return [v, -(c*v + k*x)/m]

    sol = integrate.solve_ivp(f, (0, T), (x0, v0), t_eval=ts, rtol=1e-8, atol=1e-10)
    wn = math.sqrt(k/m)
    zeta = c/(2*math.sqrt(k*m)) if k*m > 0 else math.nan
    return {
        "natural_frequency_rad_s": wn,
        "natural_frequency_hz": wn/(2*math.pi),
        "damping_ratio": zeta,
        "time_s": sol.t.tolist(),
        "position_m": sol.y[0].tolist(),
        "velocity_m_s": sol.y[1].tolist(),
    }


def op_physics_rigid_drop(p: dict[str, Any], root: Path) -> dict[str, Any]:
    """Portable 2D rigid-body drop/collision using Pymunk/Chipmunk."""
    pymunk = _need("pymunk")
    gravity = float(p.get("g_m_s2", -9.80665))
    duration = max(0.0, float(p.get("duration_s", 3.0)))
    dt = float(p.get("timestep_s", 1/240))
    if dt <= 0:
        raise ValueError("timestep_s must be > 0")

    mass = float(p.get("mass_kg", 1.0))
    if mass <= 0:
        raise ValueError("mass_kg must be > 0")

    size = p.get("box_size_m", [0.2, 0.2])
    if len(size) < 2:
        raise ValueError("box_size_m must contain [width, height]")
    width, height = float(size[0]), float(size[1])
    if width <= 0 or height <= 0:
        raise ValueError("box dimensions must be > 0")

    start = p.get("position_m", [0.0, float(p.get("height_m", 1.0))])
    vel = p.get("velocity_m_s") or [0.0, 0.0]
    angle = math.radians(float(p.get("angle_deg", 0.0)))
    angular_velocity = math.radians(float(p.get("angular_velocity_deg_s", 0.0)))
    elasticity = max(0.0, min(1.0, float(p.get("elasticity", 0.2))))
    friction = max(0.0, float(p.get("friction", 0.7)))

    space = pymunk.Space()
    space.gravity = (0.0, gravity)

    floor = pymunk.Segment(space.static_body, (-1000.0, 0.0), (1000.0, 0.0), 0.002)
    floor.friction = friction
    floor.elasticity = elasticity
    space.add(floor)

    moment = pymunk.moment_for_box(mass, (width, height))
    body = pymunk.Body(mass, moment)
    body.position = (float(start[0]), float(start[1]))
    body.velocity = (float(vel[0]), float(vel[1]))
    body.angle = angle
    body.angular_velocity = angular_velocity

    shape = pymunk.Poly.create_box(body, (width, height))
    shape.friction = friction
    shape.elasticity = elasticity
    space.add(body, shape)

    steps = int(math.ceil(duration / dt))
    min_center_y = float(body.position.y)
    max_speed = 0.0
    contact_seen = False

    for _ in range(steps):
        space.step(dt)
        min_center_y = min(min_center_y, float(body.position.y))
        speed = math.hypot(float(body.velocity.x), float(body.velocity.y))
        max_speed = max(max_speed, speed)
        if body.position.y <= height / 2 + 0.01:
            contact_seen = True

    return {
        "engine": "Pymunk/Chipmunk",
        "dimensions": "2D",
        "final_position_m": [float(body.position.x), float(body.position.y)],
        "final_angle_deg": math.degrees(float(body.angle)),
        "final_velocity_m_s": [float(body.velocity.x), float(body.velocity.y)],
        "final_angular_velocity_deg_s": math.degrees(float(body.angular_velocity)),
        "minimum_center_height_m": min_center_y,
        "maximum_speed_m_s": max_speed,
        "ground_contact_observed": contact_seen,
        "duration_s": duration,
        "timestep_s": dt,
        "note": "Portable 2D rigid-body dynamics; general 3D multibody simulation belongs in a separate optional engine tier."
    }


def op_coupled_demo(payload, root):
    from Scientific.coupled_physics_tool import run
    return run(payload, root)


OPERATIONS: dict[str, Callable[[dict[str, Any], Path], dict[str, Any]]] = {
    "status": op_status,
    "units.convert": op_units_convert,
    "math.symbolic": op_math_symbolic,
    "stats.describe": op_stats_describe,
    "signal.fft": op_signal_fft,
    "cad.model": op_cad_model,
    "cad.blueprint": op_cad_blueprint,
    "mesh.inspect": op_mesh_inspect,
    "mechanical.beam": op_mechanical_beam,
    "mechanical.truss2d": op_mechanical_truss2d,
    "electrical.dc": op_electrical_dc,
    "electrical.rc": op_electrical_rc,
    "electrical.kicad_export": op_electrical_kicad_export,
    "chem.describe": op_chem_describe,
    "chem.render": op_chem_render,
    "chem.conformer": op_chem_conformer,
    "genome.analyze": op_genome_analyze,
    "genome.translate": op_genome_translate,
    "genome.align": op_genome_align,
    "genome.msa": op_genome_msa,
    "circuit.sbol": op_circuit_sbol,
    "protein.inspect": op_protein_inspect,
    "protein.render": op_protein_render,
    "protein.minimize": op_protein_minimize,
    "physics.projectile": op_physics_projectile,
    "physics.spring_mass": op_physics_spring_mass,
    "physics.rigid_drop": op_physics_rigid_drop,
    "physics.rigid2d": op_physics_rigid_drop,
    "physics.coupled_demo": op_coupled_demo,
}


def run_operation(operation: str, payload: dict[str, Any], portableai_root: Path | str) -> dict[str, Any]:
    op = operation.strip().lower()
    from Scientific.biology_tool import HELP, run as biology_run
    if op in HELP:
        return biology_run(op, payload, portableai_root)
    if op not in OPERATIONS:
        raise ValueError(
            f"Unknown science operation {operation!r}. "
            f"Available: {', '.join(sorted(OPERATIONS))}"
        )
    return OPERATIONS[op](payload, Path(portableai_root).resolve())
