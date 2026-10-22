from __future__ import annotations
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import private_path
from media_paths import media_runtime, media_reference

import argparse
import csv
import importlib
import importlib.metadata as md
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

VERSION = "15.128"
SCIENCE_MARK = "PORTABLEAI_SCIENCE_WORKBENCH_v15_128"


def _norm_root(v: str | Path | None) -> Path:
    if v:
        return Path(str(v).strip().strip('"')).resolve()
    env = os.environ.get("PORTABLEAI_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parents[1]


def _packages_path(root: Path, override: str | Path | None = None) -> Path:
    return Path(override).resolve() if override else (root / ("Runtime/SciencePackages" if os.name=='nt' else "Runtime/LinuxPackages/science")).resolve()


def _activate_runtime(root: Path, packages: Path) -> None:
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    os.environ.setdefault("MPLBACKEND", "Agg")
    mpl = private_path(root, 'PortableCache/Science') / "matplotlib"
    mpl.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl))
    if str(packages) not in sys.path:
        sys.path.insert(0, str(packages))


def _out_dir(root: Path, prefix: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    base = private_path(root, "Outputs") / "Science"
    base.mkdir(parents=True, exist_ok=True)
    p = base / f"{prefix}_{stamp}_{os.getpid()}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _rel_or_abs(root: Path, p: Path) -> str:
    try:
        return str(p.resolve())
    except Exception:
        return str(p)


def _json_safe(x: Any, depth: int = 0) -> Any:
    if depth > 6:
        return str(x)
    if x is None or isinstance(x, (str, bool, int)):
        return x
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return str(x)
        return x
    if isinstance(x, Path):
        return str(x)
    try:
        import numpy as np
        if isinstance(x, np.generic):
            return _json_safe(x.item(), depth + 1)
        if isinstance(x, np.ndarray):
            arr = x
            if arr.size > 2000:
                flat = arr.reshape(-1)[:2000].tolist()
                return {"shape": list(arr.shape), "truncated": True, "values": _json_safe(flat, depth + 1)}
            return _json_safe(arr.tolist(), depth + 1)
    except Exception:
        pass
    if isinstance(x, dict):
        out = {}
        for i, (k, v) in enumerate(x.items()):
            if i >= 500:
                out["__truncated__"] = True
                break
            out[str(k)] = _json_safe(v, depth + 1)
        return out
    if isinstance(x, (list, tuple, set)):
        vals = list(x)
        if len(vals) > 500:
            vals = vals[:500] + ["... truncated ..."]
        return [_json_safe(v, depth + 1) for v in vals]
    try:
        if hasattr(x, "to_dict"):
            return _json_safe(x.to_dict(), depth + 1)
    except Exception:
        pass
    return str(x)


def _result(operation: str, summary: str, *, data=None, tables=None, files=None, warnings=None, success=True, started=None):
    return {
        "success": bool(success),
        "tool": "PortableAI Science Workbench",
        "version": VERSION,
        "operation": operation,
        "summary": summary,
        "data": _json_safe(data if data is not None else {}),
        "tables": _json_safe(tables if tables is not None else []),
        "files": [str(x) for x in (files or [])],
        "warnings": list(warnings or []),
        "elapsed_s": round(time.perf_counter() - started, 4) if started is not None else None,
    }


def _disk_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for dp, _, files in os.walk(path):
        for name in files:
            try:
                total += (Path(dp) / name).stat().st_size
            except OSError:
                pass
    return total


def _pkg_version(name: str) -> str | None:
    aliases = {
        "Bio": "biopython",
        "rdkit": "rdkit",
        "statsmodels": "statsmodels",
        "matplotlib": "matplotlib",
        "numpy": "numpy",
        "scipy": "scipy",
        "sympy": "sympy",
        "pandas": "pandas",
        "pint": "Pint",
        "uncertainties": "uncertainties",
        "primer3": "primer3-py",
    }
    try:
        return md.version(aliases.get(name, name))
    except Exception:
        return None


def op_status(root: Path, packages: Path, inp: dict, started: float):
    names = ["numpy", "scipy", "sympy", "pandas", "matplotlib", "statsmodels", "pint", "uncertainties", "Bio", "rdkit", "primer3"]
    versions = {n: _pkg_version(n) for n in names}
    return _result(
        "status",
        "Science runtime is available." if all(versions.get(x) for x in ("numpy", "scipy", "sympy", "matplotlib")) else "Science runtime is partially installed.",
        data={
            "python": sys.version.split()[0],
            "packages_path": str(packages),
            "installed_bytes": _disk_size(packages),
            "versions": versions,
            "capabilities": [
                "symbolic mathematics", "numerical integration/optimization/ODE/FFT", "statistics/regression",
                "units/uncertainty propagation", "bioinformatics", "molecular descriptors/conformers",
                "2D plots and structure images", "general scientific Python fallback"
            ],
        },
        started=started,
    )


def _sympy_locals(sp):
    return {
        "pi": sp.pi, "E": sp.E, "I": sp.I, "oo": sp.oo,
        "sin": sp.sin, "cos": sp.cos, "tan": sp.tan, "asin": sp.asin, "acos": sp.acos, "atan": sp.atan,
        "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
        "exp": sp.exp, "log": sp.log, "ln": sp.log, "sqrt": sp.sqrt, "Abs": sp.Abs,
        "gamma": sp.gamma, "factorial": sp.factorial,
    }


def _parse_expr(sp, text: str):
    return sp.sympify(str(text), locals=_sympy_locals(sp), evaluate=True)


def op_calc(root: Path, packages: Path, inp: dict, started: float):
    import sympy as sp
    expr = _parse_expr(sp, inp.get("expression", "0"))
    subs = inp.get("substitutions") or {}
    if isinstance(subs, dict):
        expr2 = expr.subs({sp.Symbol(str(k)): _parse_expr(sp, str(v)) for k, v in subs.items()})
    else:
        expr2 = expr
    precision = max(3, min(80, int(inp.get("precision", 15))))
    simplified = sp.simplify(expr2)
    numeric = sp.N(simplified, precision)
    return _result("calc", f"Evaluated {inp.get('expression', '0')}", data={
        "exact": str(simplified), "numeric": str(numeric), "latex": sp.latex(simplified),
        "free_symbols": sorted(str(x) for x in simplified.free_symbols),
    }, started=started)


def op_solve(root: Path, packages: Path, inp: dict, started: float):
    import sympy as sp
    equations = inp.get("equations") or [inp.get("equation") or "x=0"]
    if isinstance(equations, str):
        equations = [equations]
    parsed = []
    for e in equations:
        s = str(e)
        if "=" in s:
            a, b = s.split("=", 1)
            parsed.append(sp.Eq(_parse_expr(sp, a), _parse_expr(sp, b)))
        else:
            parsed.append(_parse_expr(sp, s))
    symbols = inp.get("symbols") or []
    if isinstance(symbols, str):
        symbols = [symbols]
    syms = [sp.Symbol(str(s)) for s in symbols]
    if not syms:
        free = set()
        for e in parsed:
            free.update(getattr(e, "free_symbols", set()))
        syms = sorted(free, key=lambda z: str(z))
    sol = sp.solve(parsed, syms, dict=True) if syms else sp.solve(parsed, dict=True)
    rows = [{str(k): str(v) for k, v in row.items()} for row in sol] if isinstance(sol, list) else _json_safe(sol)
    return _result("solve", f"Solved {len(parsed)} equation(s) for {', '.join(map(str, syms)) or 'free symbols'}.", data={"solutions": rows}, tables=[{"name": "solutions", "rows": rows if isinstance(rows, list) else []}], started=started)


def op_calculus(root: Path, packages: Path, inp: dict, started: float):
    import sympy as sp
    action = str(inp.get("action") or "diff").lower()
    expr = _parse_expr(sp, inp.get("expression", "x"))
    var = sp.Symbol(str(inp.get("variable") or "x"))
    if action in ("diff", "differentiate", "derivative"):
        out = sp.diff(expr, var, int(inp.get("order") or 1))
    elif action in ("integrate", "integral"):
        bounds = inp.get("bounds")
        if bounds and len(bounds) == 2:
            out = sp.integrate(expr, (var, _parse_expr(sp, str(bounds[0])), _parse_expr(sp, str(bounds[1]))))
        else:
            out = sp.integrate(expr, var)
    elif action == "limit":
        point = _parse_expr(sp, str(inp.get("point", "0")))
        direction = str(inp.get("direction") or "+-")
        out = sp.limit(expr, var, point, dir=direction)
    elif action == "series":
        point = _parse_expr(sp, str(inp.get("point", "0")))
        out = sp.series(expr, var, point, int(inp.get("order") or 6))
    else:
        raise ValueError(f"unknown calculus action: {action}")
    return _result("calculus", f"Computed {action}.", data={"result": str(out), "latex": sp.latex(out)}, started=started)


def op_units(root: Path, packages: Path, inp: dict, started: float):
    import pint
    ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
    value = str(inp.get("value") or "1 meter")
    target = str(inp.get("to") or "")
    q = ureg(value)
    out = q.to(target) if target else q.to_base_units()
    return _result("units", f"Converted {value}.", data={"input": str(q), "result": str(out), "magnitude": float(out.magnitude), "units": str(out.units)}, started=started)


def op_uncertainty(root: Path, packages: Path, inp: dict, started: float):
    from uncertainties import ufloat
    from uncertainties import umath
    import math as pymath
    variables = inp.get("variables") or {}
    ns = {k: ufloat(float(v["value"] if isinstance(v, dict) else v[0]), float(v.get("std", v.get("sigma", 0.0)) if isinstance(v, dict) else v[1])) for k, v in variables.items()}
    allowed = {k: getattr(umath, k) for k in ("sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh", "exp", "log", "sqrt") if hasattr(umath, k)}
    allowed.update(ns)
    allowed.update({"pi": pymath.pi, "e": pymath.e})
    expr = str(inp.get("expression") or "0")
    if not re.fullmatch(r"[A-Za-z0-9_+\-*/()., \t^]+", expr):
        raise ValueError("uncertainty expression contains unsupported characters")
    val = eval(expr.replace("^", "**"), {"__builtins__": {}}, allowed)
    return _result("uncertainty", "Propagated independent standard uncertainties.", data={"nominal": float(val.n), "std_dev": float(val.s), "formatted": str(val)}, started=started)


def _load_frame(inp: dict, root=None):
    import pandas as pd
    if isinstance(inp.get("records"), list):
        return pd.DataFrame(inp["records"])
    if isinstance(inp.get("data"), dict):
        return pd.DataFrame(inp["data"])
    path = inp.get("path")
    if path:
        p = media_reference(_norm_root(root), str(path))
        if not p.exists():
            raise FileNotFoundError(p)
        suf = p.suffix.lower()
        if suf in (".xlsx", ".xlsm"):
            from Scientific.table_workbook import frame
            return frame(inp, _norm_root(root))
        if suf in (".xls", ".xlsb"):
            raise ValueError("Save the workbook as .xlsx; legacy .xls/.xlsb is not supported")
        if suf == ".json":
            return pd.read_json(p)
        if suf in (".tsv", ".tab"):
            return pd.read_csv(p, sep="\t")
        return pd.read_csv(p)
    vals = inp.get("values")
    if vals is not None:
        return pd.DataFrame({"value": vals})
    return pd.DataFrame()


def _save_table_csv(df, out: Path, name: str) -> Path:
    p = out / name
    df.to_csv(p, index=False)
    return p


def op_stats(root: Path, packages: Path, inp: dict, started: float):
    import numpy as np
    import pandas as pd
    from scipy import stats
    action = str(inp.get("action") or "describe").lower()
    files = []
    tables = []
    out = _out_dir(root, "stats")
    if action == "describe":
        df = _load_frame(inp, root)
        if df.empty:
            raise ValueError("no data supplied")
        desc = df.describe(include="all").transpose().reset_index(names="column")
        p = _save_table_csv(desc, out, "describe.csv"); files.append(p)
        rows = desc.where(pd.notnull(desc), None).to_dict(orient="records")
        tables.append({"name": "descriptive_statistics", "rows": rows})
        return _result("stats", f"Described {len(df)} row(s) across {len(df.columns)} column(s).", data={"rows": len(df), "columns": list(df.columns), "action": action}, tables=tables, files=files, started=started)
    if action in ("ttest", "t-test"):
        kind = str(inp.get("kind") or "independent").lower()
        a = np.asarray(inp.get("a") or [], dtype=float)
        b = np.asarray(inp.get("b") or [], dtype=float) if inp.get("b") is not None else None
        if kind in ("one_sample", "onesample", "one-sample"):
            res = stats.ttest_1samp(a, float(inp.get("popmean", 0.0)), nan_policy="omit")
        elif kind in ("paired", "related"):
            res = stats.ttest_rel(a, b, nan_policy="omit")
        else:
            res = stats.ttest_ind(a, b, equal_var=bool(inp.get("equal_var", False)), nan_policy="omit")
        return _result("stats", f"Computed {kind} t-test.", data={"statistic": float(res.statistic), "pvalue": float(res.pvalue), "df": float(getattr(res, "df", float("nan")))}, started=started)
    if action in ("correlation", "corr"):
        a = np.asarray(inp.get("a") or [], dtype=float); b = np.asarray(inp.get("b") or [], dtype=float)
        method = str(inp.get("method") or "pearson").lower()
        if method == "spearman": res = stats.spearmanr(a, b, nan_policy="omit")
        elif method == "kendall": res = stats.kendalltau(a, b, nan_policy="omit")
        else: res = stats.pearsonr(a, b)
        return _result("stats", f"Computed {method} correlation.", data={"correlation": float(res.statistic), "pvalue": float(res.pvalue), "n": int(min(len(a), len(b)))}, started=started)
    if action in ("anova", "anova_oneway", "oneway"):
        groups = [np.asarray(g, dtype=float) for g in (inp.get("groups") or [])]
        if len(groups) < 2: raise ValueError("anova requires at least two groups")
        res = stats.f_oneway(*groups)
        return _result("stats", "Computed one-way ANOVA.", data={"F": float(res.statistic), "pvalue": float(res.pvalue), "group_sizes": [int(len(g)) for g in groups]}, started=started)
    if action in ("linear_regression", "regression", "ols"):
        import statsmodels.api as sm
        df = _load_frame(inp, root)
        ycol = str(inp.get("y") or "")
        xcols = inp.get("x") or []
        if isinstance(xcols, str): xcols = [xcols]
        if ycol not in df.columns or not xcols or any(x not in df.columns for x in xcols):
            raise ValueError("provide existing y and x column names")
        work = df[[ycol] + list(xcols)].dropna().copy()
        X = work[list(xcols)].astype(float)
        if bool(inp.get("add_constant", True)): X = sm.add_constant(X, has_constant="add")
        y = work[ycol].astype(float)
        model = sm.OLS(y, X).fit()
        coef = pd.DataFrame({"term": model.params.index, "coefficient": model.params.values, "std_error": model.bse.values, "t": model.tvalues.values, "pvalue": model.pvalues.values, "ci_low": model.conf_int().iloc[:,0].values, "ci_high": model.conf_int().iloc[:,1].values})
        pred = model.predict(X)
        pred_df = pd.DataFrame({"observed": y.values, "predicted": pred.values, "residual": (y-pred).values})
        files += [_save_table_csv(coef, out, "coefficients.csv"), _save_table_csv(pred_df, out, "predictions.csv")]
        tables.append({"name": "coefficients", "rows": coef.to_dict(orient="records")})
        if bool(inp.get("plot", True)):
            import matplotlib; matplotlib.use("Agg", force=True)
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(7.5, 5.0))
            ax.scatter(pred, y, s=24, alpha=0.8)
            lo = float(min(pred.min(), y.min())); hi = float(max(pred.max(), y.max()))
            ax.plot([lo, hi], [lo, hi], linestyle="--", linewidth=1)
            ax.set_xlabel("Predicted"); ax.set_ylabel("Observed"); ax.set_title("Observed vs predicted")
            fig.tight_layout(); pp = out / "regression_observed_vs_predicted.png"; fig.savefig(pp, dpi=140); plt.close(fig); files.append(pp)
        return _result("stats", f"OLS regression fit on {len(work)} complete row(s).", data={"n": int(model.nobs), "r_squared": float(model.rsquared), "adj_r_squared": float(model.rsquared_adj), "f_pvalue": float(model.f_pvalue) if model.f_pvalue is not None else None, "aic": float(model.aic), "bic": float(model.bic)}, tables=tables, files=files, started=started)
    if action in ("bootstrap_ci", "bootstrap"):
        vals = np.asarray(inp.get("values") or [], dtype=float)
        vals = vals[np.isfinite(vals)]
        if len(vals) < 2: raise ValueError("bootstrap requires at least two finite values")
        n = max(100, min(100000, int(inp.get("resamples") or 5000)))
        confidence = float(inp.get("confidence") or 0.95)
        rng = np.random.default_rng(int(inp.get("seed") or 12345))
        samples = rng.choice(vals, size=(n, len(vals)), replace=True)
        stat = np.mean(samples, axis=1)
        alpha = (1-confidence)/2
        lo, hi = np.quantile(stat, [alpha, 1-alpha])
        return _result("stats", f"Bootstrap mean CI from {n} resamples.", data={"mean": float(vals.mean()), "confidence": confidence, "ci_low": float(lo), "ci_high": float(hi), "n": len(vals), "resamples": n}, started=started)
    raise ValueError(f"unknown stats action: {action}")


def op_plot(root: Path, packages: Path, inp: dict, started: float):
    import numpy as np
    import pandas as pd
    import matplotlib; matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    kind = str(inp.get("kind") or "line").lower()
    out = _out_dir(root, "plot")
    files = []
    fig, ax = plt.subplots(figsize=(8.2, 5.2))
    if kind == "function":
        import sympy as sp
        var = sp.Symbol(str(inp.get("variable") or "x")); expr = _parse_expr(sp, inp.get("expression", "x"))
        rng = inp.get("range") or [-10,10]; n = max(50, min(10000, int(inp.get("points") or 800)))
        x = np.linspace(float(rng[0]), float(rng[1]), n)
        fn = sp.lambdify(var, expr, modules=["numpy"]); y = np.asarray(fn(x), dtype=float)
        ax.plot(x, y); df = pd.DataFrame({str(var): x, "y": y})
    elif kind == "hist":
        vals = np.asarray(inp.get("values") or [], dtype=float); vals = vals[np.isfinite(vals)]
        ax.hist(vals, bins=int(inp.get("bins") or 30)); df = pd.DataFrame({"value": vals})
    else:
        x = inp.get("x")
        y = inp.get("y")
        if y is None:
            y = inp.get("values") or []
        y = np.asarray(y, dtype=float)
        if x is None: x = np.arange(len(y))
        xarr = np.asarray(x)
        if kind == "scatter": ax.scatter(xarr, y)
        elif kind == "bar": ax.bar(xarr, y)
        else: ax.plot(xarr, y, marker="o" if len(y) <= 30 else None)
        df = pd.DataFrame({"x": xarr, "y": y})
    ax.set_title(str(inp.get("title") or "Science result"))
    ax.set_xlabel(str(inp.get("xlabel") or "")); ax.set_ylabel(str(inp.get("ylabel") or ""))
    if bool(inp.get("grid", True)): ax.grid(True, alpha=0.2)
    fig.tight_layout(); png = out / "plot.png"; fig.savefig(png, dpi=150); plt.close(fig); files.append(png)
    csvp = out / "data.csv"; df.to_csv(csvp, index=False); files.append(csvp)
    return _result("plot", f"Rendered {kind} plot with {len(df)} row(s).", data={"kind": kind, "rows": len(df)}, files=files, started=started)


def _clean_seq(s: str) -> str:
    return re.sub(r"[^A-Za-z*]", "", str(s or "")).upper()


def _seq_kind(s: str) -> str:
    chars = set(s.upper())
    if chars <= set("ACGTNRYKMSWBDHV-"): return "DNA"
    if chars <= set("ACGUNRYKMSWBDHV-"): return "RNA"
    return "protein"


def _gc_fraction(s: str) -> float | None:
    canon = [c for c in s.upper() if c in "ACGTU"]
    if not canon: return None
    return (canon.count("G") + canon.count("C")) / len(canon)


def op_bio(root: Path, packages: Path, inp: dict, started: float):
    from Bio.Seq import Seq
    from Bio import SeqIO
    action = str(inp.get("action") or "analyze_sequence").lower()
    if action in ("analyze", "analyze_sequence", "sequence"):
        s = _clean_seq(inp.get("sequence") or "")
        if not s: raise ValueError("sequence is empty")
        kind = _seq_kind(s); data = {"kind": kind, "length": len(s)}
        if kind in ("DNA", "RNA"):
            data["gc_fraction"] = _gc_fraction(s); data["gc_percent"] = None if data["gc_fraction"] is None else 100*data["gc_fraction"]
            data["reverse_complement"] = str(Seq(s).reverse_complement())
            if kind == "DNA":
                usable = s[:len(s)//3*3]
                data["translation_frame_1"] = str(Seq(usable).translate()) if usable else ""
        return _result("bio", f"Analyzed {kind} sequence of length {len(s)}.", data=data, started=started)
    if action in ("reverse_complement", "revcomp"):
        s = _clean_seq(inp.get("sequence") or "")
        return _result("bio", "Computed reverse complement.", data={"sequence": str(Seq(s).reverse_complement())}, started=started)
    if action == "translate":
        s = _clean_seq(inp.get("sequence") or ""); frame = int(inp.get("frame") or 1)
        if frame not in (1,2,3,-1,-2,-3): raise ValueError("frame must be 1,2,3,-1,-2,-3")
        q = Seq(s) if frame > 0 else Seq(s).reverse_complement(); offset = abs(frame)-1; q = q[offset:]
        q = q[:len(q)//3*3]
        prot = str(q.translate(table=int(inp.get("table") or 1), to_stop=bool(inp.get("to_stop", False)))) if q else ""
        return _result("bio", f"Translated frame {frame}.", data={"protein": prot, "aa_length": len(prot)}, started=started)
    if action in ("align", "pairwise_align"):
        from Bio import Align
        a = _clean_seq(inp.get("a") or inp.get("seq1") or ""); b = _clean_seq(inp.get("b") or inp.get("seq2") or "")
        al = Align.PairwiseAligner(); al.mode = str(inp.get("mode") or "global").lower()
        if inp.get("match_score") is not None: al.match_score = float(inp["match_score"])
        if inp.get("mismatch_score") is not None: al.mismatch_score = float(inp["mismatch_score"])
        if inp.get("open_gap_score") is not None: al.open_gap_score = float(inp["open_gap_score"])
        if inp.get("extend_gap_score") is not None: al.extend_gap_score = float(inp["extend_gap_score"])
        aligns = al.align(a,b); best = aligns[0]
        txt = str(best)
        return _result("bio", f"Computed {al.mode} pairwise alignment.", data={"score": float(best.score), "alignment": txt[:12000]}, started=started)
    if action in ("fasta_summary", "fasta"):
        import pandas as pd
        path = media_reference(root, str(inp.get("path") or ""));
        if not path.exists(): raise FileNotFoundError(path)
        rows=[]
        for rec in SeqIO.parse(str(path), "fasta"):
            seq = str(rec.seq).upper(); rows.append({"id":rec.id,"description":rec.description,"length":len(seq),"gc_percent":None if _gc_fraction(seq) is None else 100*_gc_fraction(seq)})
        df=pd.DataFrame(rows); out=_out_dir(root,"fasta"); csvp=out/"fasta_summary.csv"; df.to_csv(csvp,index=False); files=[csvp]
        if len(df):
            import matplotlib; matplotlib.use("Agg",force=True); import matplotlib.pyplot as plt
            fig,ax=plt.subplots(figsize=(7.5,4.5)); ax.hist(df["length"].astype(float),bins=min(30,max(5,int(math.sqrt(len(df)))))); ax.set_title("FASTA sequence lengths"); ax.set_xlabel("Length"); ax.set_ylabel("Count"); fig.tight_layout(); pp=out/"length_histogram.png"; fig.savefig(pp,dpi=140); plt.close(fig); files.append(pp)
        return _result("bio", f"Summarized {len(df)} FASTA record(s).", data={"records":len(df),"total_bases":int(df["length"].sum()) if len(df) else 0}, tables=[{"name":"fasta_summary","rows":rows[:200]}], files=files, started=started)
    if action in ("motif", "find_motif"):
        s=_clean_seq(inp.get("sequence") or ""); motif=_clean_seq(inp.get("motif") or "")
        if not motif: raise ValueError("motif is empty")
        hits=[m.start() for m in re.finditer(f"(?={re.escape(motif)})",s)]
        return _result("bio", f"Found {len(hits)} motif occurrence(s).", data={"motif":motif,"zero_based_positions":hits,"one_based_positions":[x+1 for x in hits]}, started=started)
    if action in ("codon_usage", "codons"):
        from collections import Counter
        s=_clean_seq(inp.get("sequence") or "").replace("U","T"); offset=int(inp.get("frame") or 1)-1; q=s[offset:]; q=q[:len(q)//3*3]; c=Counter(q[i:i+3] for i in range(0,len(q),3))
        rows=[{"codon":k,"count":v,"fraction":v/max(1,sum(c.values()))} for k,v in sorted(c.items())]
        return _result("bio", "Computed codon usage.", data={"codons":sum(c.values())}, tables=[{"name":"codon_usage","rows":rows}], started=started)
    if action in ("primer", "primer_design"):
        try: import primer3
        except Exception as exc: raise RuntimeError("primer3-py is not installed in the Science runtime") from exc
        template=_clean_seq(inp.get("sequence") or "")
        args={"SEQUENCE_ID":"PortableAI","SEQUENCE_TEMPLATE":template}
        if inp.get("target"):
            args["SEQUENCE_TARGET"]=[int(inp["target"][0]),int(inp["target"][1])]
        global_args={
            "PRIMER_OPT_SIZE": int(inp.get("opt_size") or 20), "PRIMER_MIN_SIZE": int(inp.get("min_size") or 18), "PRIMER_MAX_SIZE": int(inp.get("max_size") or 25),
            "PRIMER_MIN_TM": float(inp.get("min_tm") or 57.0), "PRIMER_OPT_TM": float(inp.get("opt_tm") or 60.0), "PRIMER_MAX_TM": float(inp.get("max_tm") or 63.0),
            "PRIMER_PRODUCT_SIZE_RANGE": inp.get("product_size_range") or [[100,1000]], "PRIMER_NUM_RETURN": int(inp.get("num_return") or 5),
        }
        res=primer3.bindings.design_primers(args,global_args); rows=[]
        n=int(res.get("PRIMER_PAIR_NUM_RETURNED",0))
        for i in range(n): rows.append({"pair":i+1,"left":res.get(f"PRIMER_LEFT_{i}_SEQUENCE"),"right":res.get(f"PRIMER_RIGHT_{i}_SEQUENCE"),"product_size":res.get(f"PRIMER_PAIR_{i}_PRODUCT_SIZE"),"left_tm":res.get(f"PRIMER_LEFT_{i}_TM"),"right_tm":res.get(f"PRIMER_RIGHT_{i}_TM")})
        return _result("bio", f"Designed {n} primer pair(s).", data={"returned":n}, tables=[{"name":"primer_pairs","rows":rows}], started=started)
    raise ValueError(f"unknown bio action: {action}")


def _chem_mol(smiles: str):
    from rdkit import Chem
    m=Chem.MolFromSmiles(str(smiles));
    if m is None: raise ValueError("invalid SMILES")
    return m


def _draw_mol(mol, path: Path, legend: str = ""):
    from rdkit.Chem import Draw
    img=Draw.MolToImage(mol,size=(700,450),legend=legend)
    img.save(path)


def op_chem(root: Path, packages: Path, inp: dict, started: float):
    from rdkit import Chem
    from rdkit.Chem import Descriptors, Crippen, Lipinski, rdMolDescriptors, AllChem, QED
    action=str(inp.get("action") or "descriptors").lower(); out=_out_dir(root,"chem")
    if action in ("descriptors","describe","molecule"):
        smi=str(inp.get("smiles") or ""); mol=_chem_mol(smi); can=Chem.MolToSmiles(mol,canonical=True)
        data={"canonical_smiles":can,"formula":rdMolDescriptors.CalcMolFormula(mol),"molecular_weight":Descriptors.MolWt(mol),"exact_mass":Descriptors.ExactMolWt(mol),"logP":Crippen.MolLogP(mol),"tpsa":rdMolDescriptors.CalcTPSA(mol),"h_bond_donors":Lipinski.NumHDonors(mol),"h_bond_acceptors":Lipinski.NumHAcceptors(mol),"rotatable_bonds":Lipinski.NumRotatableBonds(mol),"ring_count":rdMolDescriptors.CalcNumRings(mol),"fraction_csp3":rdMolDescriptors.CalcFractionCSP3(mol),"qed":QED.qed(mol),"formal_charge":Chem.GetFormalCharge(mol)}
        pp=out/"structure.png"; _draw_mol(mol,pp,can)
        return _result("chem", "Computed molecular descriptors and 2D structure.", data=data, files=[pp], started=started)
    if action in ("conformer","minimize","3d"):
        smi=str(inp.get("smiles") or ""); mol=Chem.AddHs(_chem_mol(smi)); params=AllChem.ETKDGv3(); params.randomSeed=int(inp.get("seed") or 61453); code=AllChem.EmbedMolecule(mol,params)
        if code != 0: raise RuntimeError("RDKit conformer embedding failed")
        method="MMFF"; energy=None
        if AllChem.MMFFHasAllMoleculeParams(mol):
            props=AllChem.MMFFGetMoleculeProperties(mol); ff=AllChem.MMFFGetMoleculeForceField(mol,props); ff.Minimize(maxIts=int(inp.get("max_iters") or 500)); energy=float(ff.CalcEnergy())
        else:
            method="UFF"; ff=AllChem.UFFGetMoleculeForceField(mol); ff.Minimize(maxIts=int(inp.get("max_iters") or 500)); energy=float(ff.CalcEnergy())
        sdf=out/"conformer.sdf"; writer=Chem.SDWriter(str(sdf)); writer.write(mol); writer.close(); png=out/"structure.png"; _draw_mol(Chem.RemoveHs(mol),png,Chem.MolToSmiles(Chem.RemoveHs(mol)))
        return _result("chem", f"Generated and minimized a 3D conformer with {method}.", data={"method":method,"energy_kcal_mol":energy,"canonical_smiles":Chem.MolToSmiles(Chem.RemoveHs(mol))}, files=[png,sdf], started=started)
    if action in ("similarity","compare"):
        from rdkit.Chem import rdFingerprintGenerator
        from rdkit import DataStructs
        query=_chem_mol(inp.get("smiles") or inp.get("query") or ""); refs=inp.get("references") or inp.get("smiles_list") or []
        gen=rdFingerprintGenerator.GetMorganGenerator(radius=int(inp.get("radius") or 2),fpSize=int(inp.get("fp_size") or 2048)); qfp=gen.GetFingerprint(query); rows=[]
        for s in refs:
            m=_chem_mol(str(s)); sim=float(DataStructs.TanimotoSimilarity(qfp,gen.GetFingerprint(m))); rows.append({"smiles":Chem.MolToSmiles(m),"tanimoto":sim})
        rows.sort(key=lambda r:r["tanimoto"],reverse=True)
        return _result("chem", f"Compared query against {len(rows)} molecule(s).", tables=[{"name":"similarity","rows":rows}], data={"query":Chem.MolToSmiles(query)}, started=started)
    if action in ("substructure","smarts"):
        patt=Chem.MolFromSmarts(str(inp.get("smarts") or ""));
        if patt is None: raise ValueError("invalid SMARTS")
        refs=inp.get("smiles_list") or []; rows=[]
        for s in refs:
            m=_chem_mol(str(s)); matches=m.GetSubstructMatches(patt); rows.append({"smiles":Chem.MolToSmiles(m),"match":bool(matches),"match_count":len(matches),"atom_matches":[list(x) for x in matches[:20]]})
        return _result("chem", f"Substructure search across {len(rows)} molecule(s).", tables=[{"name":"substructure","rows":rows}], started=started)
    raise ValueError(f"unknown chem action: {action}")


def op_numerics(root: Path, packages: Path, inp: dict, started: float):
    import numpy as np
    import sympy as sp
    from scipy import integrate, optimize, fft
    action=str(inp.get("action") or "quad").lower(); var=sp.Symbol(str(inp.get("variable") or "x"))
    if action in ("quad","integrate"):
        expr=_parse_expr(sp,inp.get("expression","x")); fn=sp.lambdify(var,expr,modules=["numpy"]); bounds=inp.get("bounds") or [0,1]; val,err=integrate.quad(lambda x: float(fn(x)),float(bounds[0]),float(bounds[1]))
        return _result("numerics","Computed numerical quadrature.",data={"value":val,"estimated_abs_error":err},started=started)
    if action in ("root","root_scalar"):
        expr=_parse_expr(sp,inp.get("expression","x")); fn=sp.lambdify(var,expr,modules=["numpy"]); bracket=inp.get("bracket")
        if bracket: res=optimize.root_scalar(fn,bracket=[float(bracket[0]),float(bracket[1])],method=str(inp.get("method") or "brentq"))
        else: res=optimize.root_scalar(fn,x0=float(inp.get("x0") or 0),x1=float(inp.get("x1") or 1))
        return _result("numerics","Solved scalar root.",data={"root":float(res.root),"converged":bool(res.converged),"iterations":int(res.iterations)},started=started)
    if action in ("minimize","optimize"):
        vars=[sp.Symbol(str(v)) for v in (inp.get("variables") or ["x"])]; expr=_parse_expr(sp,inp.get("expression","x**2")); fn=sp.lambdify(vars,expr,modules=["numpy"]); x0=np.asarray(inp.get("x0") or [0.0]*len(vars),dtype=float)
        res=optimize.minimize(lambda x: float(fn(*x)),x0,method=str(inp.get("method") or "BFGS"))
        return _result("numerics","Minimized objective.",data={"x":res.x.tolist(),"fun":float(res.fun),"success":bool(res.success),"message":str(res.message),"iterations":int(getattr(res,"nit",0))},started=started)
    if action in ("ode","solve_ivp"):
        t=sp.Symbol("t"); y=sp.Symbol("y"); expr=_parse_expr(sp,inp.get("dydt","-y")); fn=sp.lambdify((t,y),expr,modules=["numpy"]); span=inp.get("t_span") or [0,10]; y0=[float(inp.get("y0") or 1.0)]; n=max(20,min(10000,int(inp.get("points") or 500))); te=np.linspace(float(span[0]),float(span[1]),n); res=integrate.solve_ivp(lambda tt,yy:[float(fn(tt,yy[0]))],[float(span[0]),float(span[1])],y0,t_eval=te,rtol=float(inp.get("rtol") or 1e-7),atol=float(inp.get("atol") or 1e-9)); out=_out_dir(root,"ode")
        import pandas as pd; df=pd.DataFrame({"t":res.t,"y":res.y[0]}); csvp=out/"ode.csv"; df.to_csv(csvp,index=False)
        import matplotlib; matplotlib.use("Agg",force=True); import matplotlib.pyplot as plt; fig,ax=plt.subplots(figsize=(7.5,4.5)); ax.plot(res.t,res.y[0]); ax.set_xlabel("t"); ax.set_ylabel("y"); ax.set_title("ODE solution"); ax.grid(True,alpha=.2); fig.tight_layout(); pp=out/"ode.png"; fig.savefig(pp,dpi=140); plt.close(fig)
        return _result("numerics","Integrated first-order ODE.",data={"success":bool(res.success),"message":str(res.message),"final_y":float(res.y[0,-1])},files=[pp,csvp],started=started)
    if action == "fft":
        vals=np.asarray(inp.get("values") or [],dtype=float); dt=float(inp.get("dt") or 1.0); yf=fft.rfft(vals); freq=fft.rfftfreq(len(vals),dt); amp=np.abs(yf)/max(1,len(vals)); idx=np.argsort(amp)[::-1][:min(20,len(amp))]; rows=[{"frequency":float(freq[i]),"amplitude":float(amp[i])} for i in idx]
        return _result("numerics","Computed real FFT.",tables=[{"name":"dominant_frequencies","rows":rows}],data={"n":len(vals),"dt":dt},started=started)
    raise ValueError(f"unknown numerics action: {action}")


def op_linear(root: Path, packages: Path, inp: dict, started: float):
    import numpy as np
    action=str(inp.get("action") or "eigen").lower(); A=np.asarray(inp.get("matrix") or [],dtype=float)
    if A.ndim != 2: raise ValueError("matrix must be 2D")
    if action in ("eigen","eig"):
        vals,vecs=np.linalg.eig(A); return _result("linear_algebra","Computed eigen decomposition.",data={"eigenvalues":vals,"eigenvectors":vecs},started=started)
    if action in ("inverse","inv"):
        return _result("linear_algebra","Computed matrix inverse.",data={"inverse":np.linalg.inv(A)},started=started)
    if action in ("det","determinant"):
        return _result("linear_algebra","Computed determinant.",data={"determinant":float(np.linalg.det(A))},started=started)
    if action in ("solve","linsolve"):
        b=np.asarray(inp.get("b") or [],dtype=float); return _result("linear_algebra","Solved linear system.",data={"x":np.linalg.solve(A,b)},started=started)
    if action in ("svd",):
        u,s,vh=np.linalg.svd(A); return _result("linear_algebra","Computed singular value decomposition.",data={"U":u,"singular_values":s,"Vh":vh},started=started)
    raise ValueError(f"unknown linear algebra action: {action}")


def op_physics(root: Path, packages: Path, inp: dict, started: float):
    from scipy import constants
    action=str(inp.get("action") or "constant").lower()
    if action in ("constant","constants"):
        query=str(inp.get("query") or "").strip().lower(); rows=[]
        for name,(val,unit,unc) in constants.physical_constants.items():
            if not query or query in name.lower(): rows.append({"name":name,"value":val,"unit":unit,"uncertainty":unc})
            if len(rows)>=100: break
        simple={k:getattr(constants,k) for k in ("c","h","hbar","G","e","m_e","m_p","k","N_A","R","epsilon_0","mu_0") if hasattr(constants,k)}
        return _result("physics",f"Found {len(rows)} physical constant match(es).",data={"common_constants":simple},tables=[{"name":"physical_constants","rows":rows}],started=started)
    if action == "kinematics":
        # Constant-acceleration 1D utility. Solve whichever one of x, x0, v, v0, a, t is missing when possible.
        import sympy as sp
        x,x0,v,v0,a,t=sp.symbols("x x0 v v0 a t")
        vals={}; mapping={"x":x,"x0":x0,"v":v,"v0":v0,"a":a,"t":t}
        for k,sym in mapping.items():
            if inp.get(k) is not None: vals[sym]=float(inp[k])
        eqs=[sp.Eq(v,v0+a*t),sp.Eq(x,x0+v0*t+sp.Rational(1,2)*a*t**2),sp.Eq(v**2,v0**2+2*a*(x-x0))]
        missing=[sym for sym in mapping.values() if sym not in vals]
        if len(missing)!=1: raise ValueError("kinematics expects exactly one of x,x0,v,v0,a,t to be unknown")
        sols=sp.solve([e.subs(vals) for e in eqs],[missing[0]],dict=True)
        return _result("physics",f"Solved constant-acceleration kinematics for {missing[0]}.",data={"solutions":[{str(k):str(vv) for k,vv in row.items()} for row in sols]},started=started)
    raise ValueError(f"unknown physics action: {action}")


def op_run(root: Path, packages: Path, inp: dict, started: float):
    code=str(inp.get("code") or "")
    if not code.strip(): raise ValueError("code is empty")
    if len(code)>120000: raise ValueError("code exceeds 120000 characters")
    out=_out_dir(root,"run"); script=out/"science_user_code.py"
    prelude=f'''from pathlib import Path\nOUT = Path(r"{str(out)}")\nimport numpy as np\nimport scipy\nimport sympy as sp\nimport pandas as pd\nimport matplotlib\nmatplotlib.use("Agg", force=True)\nimport matplotlib.pyplot as plt\ntry:\n import statsmodels.api as sm\nexcept Exception: sm=None\ntry:\n from Bio import SeqIO\n from Bio.Seq import Seq\nexcept Exception: SeqIO=Seq=None\ntry:\n from rdkit import Chem\n from rdkit.Chem import AllChem, Descriptors, Draw\nexcept Exception: Chem=AllChem=Descriptors=Draw=None\n'''
    prelude='import sys\nsys.path.insert(0, '+repr(str(packages))+')\n'+prelude
    script.write_text(prelude+"\n"+code,encoding="utf-8")
    env=os.environ.copy(); env["PYTHONPATH"]=str(packages)+(os.pathsep+env["PYTHONPATH"] if env.get("PYTHONPATH") else ""); env["PYTHONDONTWRITEBYTECODE"]="1"; env["MPLBACKEND"]="Agg"; env["MPLCONFIGDIR"]=str(private_path(root, 'PortableCache/Science')/"matplotlib")
    timeout=max(1,min(1800,int(inp.get("timeout") or 300)))
    from platform_runtime import python_path
    cp=subprocess.run([str(python_path(root)),str(script)],cwd=str(out),env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout)
    files=[]
    for p in sorted(out.iterdir()):
        if p.name==script.name: continue
        if p.is_file() and p.stat().st_size <= 512*1024*1024: files.append(p)
    summary="Scientific Python script completed." if cp.returncode==0 else f"Scientific Python script exited with code {cp.returncode}."
    return _result("run",summary,data={"returncode":cp.returncode,"stdout":cp.stdout[-50000:],"stderr":cp.stderr[-30000:]},files=files,success=cp.returncode==0,started=started)


def op_help(root: Path, packages: Path, inp: dict, started: float):
    ops={
      "calc":"symbolic/numeric expression evaluation",
      "solve":"symbolic equations/systems",
      "calculus":"differentiate, integrate, limit, series",
      "linear_algebra":"eigen/inverse/determinant/solve/SVD",
      "units":"Pint unit conversion",
      "uncertainty":"uncertainty propagation",
      "stats":"describe, t-test, correlation, ANOVA, OLS, bootstrap CI",
      "plot":"line/scatter/bar/hist/function plots -> PNG + CSV",
      "bio":"sequence analysis, translate, align, FASTA summary, motif, codon usage, primer design",
      "chem":"molecular descriptors, 2D depiction, 3D conformer/MMFF-UFF, similarity, substructure",
      "numerics":"quadrature, root solve, minimize, ODE, FFT",
      "physics":"physical constants and basic kinematics",
      "run":"general scientific Python fallback with NumPy/SciPy/SymPy/Pandas/Matplotlib preloaded",
      "status":"runtime/package inventory",
    }
    if str(root) not in sys.path: sys.path.insert(0,str(root))
    from Scientific.biology_tool import HELP
    ops.update(HELP)
    return _result("help","PortableAI Science Workbench operations.",data=ops,started=started)


def op_selftest(root: Path, packages: Path, inp: dict, started: float):
    checks={}
    import numpy as np; checks["numpy"]=str(np.__version__)
    import scipy; checks["scipy"]=str(scipy.__version__)
    import sympy as sp; checks["sympy"]=str(sp.__version__); assert sp.simplify(sp.sin(sp.pi/2))==1
    import pandas as pd; checks["pandas"]=str(pd.__version__)
    import matplotlib; checks["matplotlib"]=str(matplotlib.__version__)
    import statsmodels; checks["statsmodels"]=str(statsmodels.__version__)
    import pint; checks["pint"]=_pkg_version("pint")
    import uncertainties; checks["uncertainties"]=_pkg_version("uncertainties")
    import Bio; checks["biopython"]=str(Bio.__version__); assert str(__import__('Bio.Seq',fromlist=['Seq']).Seq("ATGC").reverse_complement())=="GCAT"
    import rdkit; checks["rdkit"]=str(rdkit.__version__); from rdkit import Chem; assert Chem.MolFromSmiles("CCO") is not None
    try: import primer3; checks["primer3"]=_pkg_version("primer3")
    except Exception: checks["primer3"]=None
    out=_out_dir(root,"selftest")
    import matplotlib.pyplot as plt; fig,ax=plt.subplots(); ax.plot([0,1],[0,1]); pp=out/"selftest.png"; fig.savefig(pp,dpi=80); plt.close(fig); assert pp.exists() and pp.stat().st_size>100
    try: shutil.rmtree(out)
    except Exception: pass
    return _result("selftest","All mandatory Science Workbench self-tests passed.",data=checks,started=started)


def dispatch(root: Path, packages: Path, req: dict):
    started=time.perf_counter(); op=str(req.get("operation") or "help").strip().lower().replace("-","_"); inp=req.get("input") or {}
    if not isinstance(inp,dict): raise ValueError("input must be a JSON object")
    # New biology routes share one implementation across native chat and CLI.
    if str(root) not in sys.path: sys.path.insert(0,str(root))
    from Scientific.biology_tool import HELP, run as biology_run
    if op in HELP:
        from scientific_tool_bridge import _activate
        _activate()
        value=biology_run(op,inp,root)
        return _result(op,'Science operation completed.',data=value,files=value.get('files',[]),started=started)
    funcs={"status":op_status,"help":op_help,"calc":op_calc,"solve":op_solve,"calculus":op_calculus,"units":op_units,"uncertainty":op_uncertainty,"stats":op_stats,"plot":op_plot,"bio":op_bio,"chem":op_chem,"numerics":op_numerics,"linear":op_linear,"linear_algebra":op_linear,"physics":op_physics,"run":op_run,"selftest":op_selftest}
    if op not in funcs: raise ValueError(f"unknown operation: {op}")
    from profile_tool_hydration import prepare_tool_files
    prepare_tool_files(root,'science',operation=op)
    return funcs[op](root,packages,inp,started)


def main():
    ap=argparse.ArgumentParser(description="PortableAI local scientific-computing bridge")
    ap.add_argument("--root"); ap.add_argument("--packages"); ap.add_argument("--request-file"); ap.add_argument("--request-json"); ap.add_argument("--operation"); ap.add_argument("--input-json",default="{}")
    ns=ap.parse_args(); root=_norm_root(ns.root); packages=_packages_path(root,ns.packages); _activate_runtime(root,packages)
    try:
        if ns.request_file: req=json.loads(media_reference(_norm_root(ns.root), ns.request_file).read_text(encoding="utf-8"))
        elif ns.request_json: req=json.loads(ns.request_json)
        else: req={"operation":ns.operation or "help","input":json.loads(ns.input_json or "{}")}
        res=dispatch(root,packages,req)
    except subprocess.TimeoutExpired as exc:
        res=_result(str(getattr(ns,"operation","") or "run"),f"Science task exceeded its timeout ({exc.timeout}s).",data={},success=False,started=time.perf_counter())
    except Exception as exc:
        res={"success":False,"tool":"PortableAI Science Workbench","version":VERSION,"operation":(locals().get("req") or {}).get("operation") if isinstance(locals().get("req"),dict) else None,"error":f"{type(exc).__name__}: {exc}","files":[]}
    print(json.dumps(_json_safe(res),ensure_ascii=False,separators=(",",":")))
    return 0 if res.get("success") else 2


if __name__=="__main__":
    raise SystemExit(main())
