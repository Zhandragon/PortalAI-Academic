"""Actual bounded KiCad exports using only synthetic files and private fixture state."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','Tools','Scientific')]
from validation_artifacts import ValidationArtifacts
from kicad_windows import command_environment


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--artifacts-dir',required=True)
    parser.add_argument('--payload',type=Path,default=ROOT/'Tools/KiCad')
    args=parser.parse_args(); artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    fixture=artifacts.path('fixture');fixture.mkdir(exist_ok=True)
    # A separate legacy-format synthetic root contains no real account state.
    command,env=command_environment(fixture,payload=args.payload.resolve())
    def run(argv):
        result=subprocess.run(argv,cwd=fixture,env=env,capture_output=True,text=True,errors='replace',
            timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise RuntimeError(result.stdout+'\n'+result.stderr)
        return result.stdout
    version=run([*command,'--version']).strip();assert version=='9.0.2',version
    # Reuse the checked-in small schematic and board with a stock resistor model.
    tree=ast.parse((ROOT/'Tools/linux_kicad_tests.py').read_text(encoding='utf-8'))
    fixtures={}
    for node in ast.walk(tree):
        if (isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='write_text'
            and isinstance(node.func.value,ast.Name) and node.func.value.id in ('sch','pcb')):
            fixtures[node.func.value.id]=ast.literal_eval(node.args[0])
    sch=fixture/'fixture.kicad_sch';sch.write_text(fixtures['sch'],encoding='utf-8')
    pcb=fixture/'fixture.kicad_pcb';pcb.write_text(fixtures['pcb'],encoding='utf-8')
    import science_core,kicad_windows
    outputs=[]
    with patch.object(science_core,'_find_kicad',return_value=command[0]), \
         patch.object(kicad_windows,'command_environment',return_value=(command,env)):
        for kind,source,extension in [('schematic-svg',sch,'.svg'),('bom',sch,'.csv'),('pcb-step',pcb,'.step')]:
            out=fixture/'Outputs'/kind
            result=science_core.op_electrical_kicad_export({'input':str(source),'kind':kind,'output_dir':str(out)},fixture)
            files=list(Path(result['output_dir']).glob('*'+extension))
            assert files and all(file.stat().st_size>0 for file in files),result
            if kind=='schematic-svg':assert '<svg' in files[0].read_text()
            if kind=='pcb-step':
                text=files[0].read_text();assert 'ISO-10303-21' in text
                assert 'R1' in text or 'R_0805' in text,'Bundled component missing from STEP'
            outputs.extend({'path':str(p.relative_to(artifacts.path())), 'bytes':p.stat().st_size,
                'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files)
    assert (fixture/'Data/Science/KiCad/config').is_dir()
    report={'passed':True,'synthetic_only':True,'version':version,'payload':str(args.payload.resolve()),
        'exports':['schematic-svg','bom','pcb-step with bundled resistor model'],'outputs':outputs,
        'state_on_portable_drive':True,'production_accounts_opened':False}
    artifacts.path('kicad-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
