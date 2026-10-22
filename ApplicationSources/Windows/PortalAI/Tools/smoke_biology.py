"""Synthetic biology/network/real CPU-weight diagnostics, never a live profile login."""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'Agent'),str(ROOT/'Tools'),str(ROOT/('Runtime/ScientificPython/packages' if os.name=='nt' else 'Runtime/LinuxPackages/science'))]
from validation_artifacts import ValidationArtifacts,add_artifact_arguments
from runtime_policy import memory_info,atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__);add_artifact_arguments(parser)
    parser.add_argument('--network',action='store_true');parser.add_argument('--protein',action='store_true')
    parser.add_argument('--wrapper',action='store_true',help='Exercise parent routing/publication and Stop with an isolated fixture root')
    args=parser.parse_args();artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    folder=artifacts.path('biology-'+uuid.uuid4().hex);folder.mkdir()
    fixture=folder/'synthetic-root';(fixture/'Agent').mkdir(parents=True)
    (fixture/'Agent/hardware_profiles.json').write_bytes((ROOT/'Agent/hardware_profiles.json').read_bytes())
    report={'passed':False,'scope':'Synthetic isolated root; real CPU model only when requested; no authenticated live chat or physical GPU validation','checks':[]}
    try:
        from Scientific.biology_tool import run
        result=run('plasmid.assemble',{'parts':[{'name':'synthetic','sequence':'AACCGGTT'}]},fixture)
        assert len(result['files'])==4
        report['checks'].append({'name':'assembly_publication','passed':True})
        if args.network:
            for op,p in [('ncbi.search',{'db':'nuccore','query':'U49845.1[Accession]','limit':1}),
                         ('ncbi.fetch',{'db':'nuccore','id':'U49845.1','start':1,'end':200}),
                         ('igem.part',{'id':'BBa_J23100'})]:
                result=run(op,p,fixture)
                if op=='ncbi.search':assert result['result']['idlist']
                elif op=='ncbi.fetch':assert result['length']==200
                else:assert result['record']['name']=='BBa_J23100' and len(result['record']['sequence'])==35
                report['checks'].append({'name':op,'passed':True,'source_url':result['source_url']})
        if args.protein or args.wrapper:
            if memory_info()[1]<4*1024**3:raise RuntimeError('Insufficient free RAM for bounded protein smoke')
            from Bio.PDB import PDBParser,PDBIO,Select
            from Scientific.protein_design import backbone
            from mission_supervisor import WorkerJob
            from platform_runtime import python_path
            structure=PDBParser(QUIET=True).get_structure('fixture',ROOT/'Runtime/ProteinDesign/vendor/inputs/PDB_monomers/pdbs/5L33.pdb')
            class Region(Select):
                def accept_residue(self,r):return r.parent.id=='A' and r.id[0]==' ' and 75<=r.id[1]<=104
            output=io.StringIO();writer=PDBIO();writer.set_structure(structure);writer.save(output,Region())
            (folder/'fixture.pdb').write_text(output.getvalue(),encoding='ascii')
            protein,positions=backbone(output.getvalue(),'A');assert len(positions)==30
            if args.wrapper:
                import threading
                from unittest.mock import patch
                # Only the synthetic root's runtime launcher is mapped to the actual
                # read-only installation. Profile capture and guards remain real.
                (fixture/'Scientific').mkdir()
                (fixture/'Agent/sdcpp_worker.py').write_bytes((ROOT/'Agent/sdcpp_worker.py').read_bytes())
                (fixture/'Scientific/protein_design_worker.py').write_text(
                    'import runpy\nrunpy.run_path('+repr(str(ROOT/'Scientific/protein_design_worker.py'))+',run_name="__main__")\n',encoding='utf-8')
                (fixture/'fixture.pdb').write_text(output.getvalue(),encoding='ascii')
                payload={'pdb':'fixture.pdb','chain':'A','seed':17,'fixed_positions':[1,2],'export':True}
                with patch('platform_runtime.python_path',return_value=python_path(ROOT)):
                    result=run('protein.design',payload,fixture)
                    assert len(result['sequences'][0]['sequence'])==30 and result['files']
                    report['checks'].append({'name':'real_protein_parent_and_publication','passed':True})
                    marker=fixture/'Agent/.runtime/qwen_last_stop.json'
                    timer=threading.Timer(.6,lambda:atomic_json(marker,{'stopped_at':time.time()}))
                    timer.start()
                    try:
                        try:run('protein.design',payload,fixture)
                        except RuntimeError as exc:
                            if 'Stop' not in str(exc):raise
                        else:raise AssertionError('Expected Stop cancellation')
                    finally:timer.join()
                    assert not list((fixture/'Cache/tmp').glob('protein_*'))
                    assert len(list((fixture/'Outputs/Science/Biology').glob('biology_*')))==2
                    report['checks'].append({'name':'protein_stop_owned_cleanup','passed':True})
            request=folder/'request.json';atomic_json(request,{'protein':protein,'count':1,'temperature':.1,'seed':17,'fixed_positions':[1,2]})
            gate=folder/'gate';launch=folder/'launch.json'
            command=[str(python_path(ROOT)),'-B','-I',str(ROOT/'Scientific/protein_design_worker.py'),str(request)]
            atomic_json(launch,{'command':command,'gate':str(gate)})
            env=os.environ.copy();env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',CUDA_VISIBLE_DEVICES='',HIP_VISIBLE_DEVICES='',OMP_NUM_THREADS='2',MKL_NUM_THREADS='2')
            for key in ('PYTHONHOME','PYTHONPATH','VIRTUAL_ENV'):env.pop(key,None)
            # Synthetic temporary/cache paths only. No live account or host temp writes.
            for key in ('TEMP','TMP','TMPDIR','HF_HOME','TORCH_HOME','XDG_CACHE_HOME'):env[key]=str(folder)
            proc=job=None;started=time.monotonic()
            if args.wrapper and not args.protein:
                report['passed']=True
                artifacts.path();atomic_json(folder/'report.json',report);artifacts.path()
                print(json.dumps({'report':str(folder/'report.json'),**report},ensure_ascii=True));return 0
            try:
                with (folder/'protein.log').open('wb') as log:
                    proc=subprocess.Popen([str(python_path(ROOT)),'-B','-I',str(ROOT/'Agent/sdcpp_worker.py'),str(launch)],
                        cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    job=WorkerJob(proc);job.limit_memory(2*1024**3);gate.touch()
                    while proc.poll() is None:
                        job.check()
                        if time.monotonic()-started>120:raise TimeoutError('Protein smoke timed out')
                        if (folder/'protein.log').stat().st_size>1024**2:raise RuntimeError('Protein log limit exceeded')
                        time.sleep(.1)
                raw=(folder/'protein.log').read_text(encoding='utf-8',errors='replace')
                if proc.returncode:raise RuntimeError(raw[-1500:])
                result=json.loads(next(s for s in raw.splitlines() if s.startswith('PORTAL_PROTEIN=')).split('=',1)[1])
                seq=result['sequences'][0]['sequence'];assert len(seq)==30 and seq[:2]==protein['seq'][:2]
                report['checks'].append({'name':'real_proteinmpnn_cpu','passed':True,'residues':30,'fixed_positions_preserved':True,
                    'elapsed_seconds':round(time.monotonic()-started,3),'memory_ceiling_bytes':2*1024**3,'model':result['model']})
            finally:
                if job:job.close()
                if proc and proc.poll() is None:proc.kill();proc.wait(timeout=10)
        report['passed']=True
    except Exception as exc:report['error']=type(exc).__name__+': '+str(exc)
    artifacts.path();atomic_json(folder/'report.json',report);artifacts.path()
    print(json.dumps({'report':str(folder/'report.json'),**report},ensure_ascii=True))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
