"""Real protein minimization on CPU and OpenCL, with exact chat restoration."""
import json
import math
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"Agent"))
from scientific_tool_bridge import _activate, run_science_request
from runtime_policy import atomic_json, require_space
from service_manager import science_workload, _listener_identity, _wait_qwen_ready

if __name__=="__main__":
    require_space(ROOT, 16*1024**2, for_outputs=True)
    before=_listener_identity()
    if not before["portable_qwen"]: raise RuntimeError("Start the owned chat server first for this handoff regression")
    _wait_qwen_ready(180)
    _activate()
    from openmm import app
    fixture=ROOT/"Maintenance/Reports/science-opencl"
    fixture.mkdir(parents=True,exist_ok=True)
    source=ROOT/"Runtime/ScientificPython/packages/openmm/app/data/test.pdb"
    pdb=app.PDBFile(str(source));m=app.Modeller(pdb.topology,pdb.positions)
    m.delete([r for r in m.topology.residues() if r.name.upper() in ("HOH","NA","CL")])
    inp=fixture/"villin.pdb"
    with inp.open("w") as file:app.PDBFile.writeFile(m.topology,m.positions,file)
    report={"passed":False,"before":before,"results":[],"scope":"OpenCL on local NVIDIA; physical Radeon still unvalidated"}
    start=time.monotonic()
    try:
        for platform in ("auto","opencl"):
            with science_workload("protein.minimize",gpu_requested=platform=="opencl",gpu_backend="openmm-opencl" if platform=="opencl" else None) as execution:
                result=run_science_request("protein.minimize",json_text=json.dumps({"input":str(inp),"platform":platform,
                    "name":"villin_"+platform,"max_iterations":10,"output_dir":str(ROOT/"Outputs/Tests/science-opencl")}))
                report["results"].append({"requested_platform":platform,"execution":execution,"result":result})
        _wait_qwen_ready(180)
        after=_listener_identity();report["after"]=after
        report["exact_command_restored"]=before["listeners"][0]["command_line"]==after["listeners"][0]["command_line"]
        report["llm_was_stopped"]=before["listeners"][0]["pid"]!=after["listeners"][0]["pid"]
        # Inspect the actual returned data rather than accepting a successful exit alone.
        payloads=[r["result"].get("data",r["result"]) for r in report["results"]]
        report["passed"]=report["exact_command_restored"] and report["llm_was_stopped"] and [p.get("platform") for p in payloads]==["CPU","OpenCL"] and all(
            math.isfinite(p["final_potential_energy_kj_mol"]) and p["final_potential_energy_kj_mol"]<=p["initial_potential_energy_kj_mol"] and Path(p["file"]).is_file() for p in payloads)
        report["elapsed_seconds"]=round(time.monotonic()-start,2)
    finally:atomic_json(ROOT/"Maintenance/Reports/science-opencl-smoke.json",report)
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if report["passed"] else 1)
