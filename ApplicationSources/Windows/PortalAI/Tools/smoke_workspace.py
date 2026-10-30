"""Real portable embedding/OCR/MCP/UI acceptance using synthetic data only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Maintenance/Tests'),str(ROOT/'Tools')]
from validation_artifacts import ValidationArtifacts


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runtime-root',type=Path,default=ROOT);parser.add_argument('--knowledge-runtime',type=Path);parser.add_argument('--artifacts-dir',required=True);parser.add_argument('--ui',action='store_true');parser.add_argument('--fixture-worker',action='store_true',help=argparse.SUPPRESS);args=parser.parse_args()
    runtime=args.runtime_root.resolve();artifacts=ValidationArtifacts(runtime,args.artifacts_dir);fixture=artifacts.path('workspace-fixture')
    if fixture.exists():raise FileExistsError('Use a fresh artifacts directory for the smoke fixture')
    if not args.fixture_worker:
        # Windows keeps imported extension DLLs locked until process exit.
        # Clean independent runtime copies from the parent after the worker ends.
        result=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),*sys.argv[1:],'--fixture-worker'])
        removed=[]
        for relative in ('Runtime/Knowledge','Voice/Piper/packages','Runtime/SciencePackages'):
            folder=fixture/relative
            if folder.exists():
                if folder.is_symlink() or not folder.resolve().is_relative_to(fixture.resolve()):raise ValueError('Fixture cleanup escapes validation root')
                def writable(function,path,error):
                    if not Path(path).resolve().is_relative_to(fixture.resolve()):raise ValueError('Unexpected fixture cleanup path')
                    os.chmod(path,stat.S_IWRITE);function(path)
                shutil.rmtree(folder,onexc=writable);removed.append(relative)
        artifacts.path('runtime-copy-cleanup.json').write_text(json.dumps({'removed_temporary_copies':removed,'live_runtime_changed':False},indent=2))
        return result.returncode
    fixture.mkdir();(fixture/'Agent').mkdir();(fixture/'Agent/hardware_profiles.json').write_text(json.dumps({'storage':{'minimum_free_gib':1,'minimum_free_fraction':.0001,'output_reserve_gib':0}}))
    def copy(src,dst):
        dst.parent.mkdir(parents=True,exist_ok=True)
        # Hard links change live-file ownership and block guarded updates.
        # Keep independent copies only for this test process's lifetime.
        expected=dst.resolve()
        if not expected.is_relative_to(fixture.resolve()):raise ValueError('Fixture copy escapes validation root')
        shutil.copytree(src,dst,copy_function=shutil.copyfile,ignore=shutil.ignore_patterns('__pycache__'))
    copy(args.knowledge_runtime or runtime/'Runtime/Knowledge',fixture/'Runtime/Knowledge')
    for name in ('numpy','numpy.libs','onnxruntime'):
        src=runtime/'Voice/Piper/packages'/name
        if src.exists():copy(src,fixture/'Voice/Piper/packages'/name)
    for name in ('PIL','pillow.libs'):
        src=runtime/'Runtime/SciencePackages'/name
        if src.exists():copy(src,fixture/'Runtime/SciencePackages'/name)
    for name in ('mcp_launch.py',):shutil.copy2(ROOT/'Agent'/name,fixture/'Agent'/name)
    report={'synthetic_only':True,'owner_profiles_accessed':False,'checks':[]}
    def passed(name):report['checks'].append(name);print('PASS',name,flush=True)
    from knowledge_embeddings import Embeddings,packages
    embedding=Embeddings(fixture);vectors=embedding.encode(['An automobile drives along a road.','The car is traveling on the street.','A jellyfish floats in the ocean.'])
    dot=lambda a,b:sum(x*y for x,y in zip(a,b))
    assert len(vectors[0])==384 and dot(vectors[0],vectors[1])>dot(vectors[0],vectors[2])+.2
    assert len(embedding.tokens('hello '*1000))==256
    passed('Real quantized MiniLM semantic similarity, dimension, tokenizer bound')
    from PIL import Image,ImageDraw,ImageFont
    doc=fixture/'documents';doc.mkdir();(doc/'travel.txt').write_text('An automobile drives along a road. Vehicles have engines.');(doc/'marine.txt').write_text('A jellyfish floats in the ocean. Marine animals live underwater.')
    image=Image.new('RGB',(1000,230),'white');draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',40) if os.name=='nt' else ImageFont.load_default(size=40)
    draw.text((40,45),'PORTABLE LABORATORY',fill='black',font=font);draw.text((40,120),'Sample temperature is 25 degrees.',fill='black',font=font)
    image.save(doc/'scan.png');image.save(doc/'scan.pdf','PDF',resolution=100);image.close()
    from knowledge_base import Knowledge
    kb=Knowledge(fixture,embedder=embedding);cid=kb.create('Synthetic references',doc)['id'];sync=kb.sync(cid)
    assert sync['documents']==4
    found=kb.search('A car traveling on a street',cid,1)['results'][0];assert found['file']=='travel.txt';assert kb.read(found['citation'])['source_sha256']
    pages=kb.search('laboratory temperature',cid,6)['results'];assert any(row['file']=='scan.pdf' and row['location']=='page 1' and '25' in row['text'] for row in pages)
    assert Knowledge(fixture,embedder=embedding).sync(cid)['changed']==0
    passed('Real PNG and scanned PDF OCR, source page citations, semantic retrieval and incremental reopen')
    from mcp_client import Transport
    from platform_runtime import python_path
    python=python_path(runtime);config={'id':'a'*32,'transport':'stdio','command':['{python}','-B','-I',str(ROOT/'Maintenance/Tests/workspace_mcp_fixture.py')]}
    with patch('platform_runtime.python_path',return_value=python):
        t=Transport(fixture,config,lambda:None)
        try:
            t.initialize();assert t.tools()[0]['name']=='echo';result=t.request('tools/call',{'name':'echo','arguments':{'text':'portable'}});assert result['content'][0]['text']=='portable';pid=t.process.pid
        finally:t.close()
        assert t.process is None
        passed('Real stdio MCP owned worker initialize/discover/call/close')
        stopped=[False]
        def check():
            if stopped[0]:raise RuntimeError('Synthetic cancellation')
        t=Transport(fixture,config,check);t.initialize()
        import threading
        timer=threading.Timer(.3,lambda:stopped.__setitem__(0,True));timer.start();started=time.monotonic()
        try:
            try:t.request('tools/call',{'name':'echo','arguments':{'text':'wait'}})
            except RuntimeError:pass
            else:raise AssertionError('Cancellation was ignored')
        finally:t.close();timer.join()
        assert time.monotonic()-started<4
        passed('Real MCP hanging worker cancellation and process cleanup')
    if args.ui:
        import tkinter as tk
        from test_settings_surfaces_tk import LIGHT,DARK
        from native_chat import ToolRuntime
        from writer_jobs import WriterJobs
        from workspace_panel import show_workspace
        from smoke_account_panels import capture_window
        from tk_fixture_cleanup import finish_tk_fixture
        app=tk.Tk();app.title('PortalAI synthetic Workspace acceptance');errors=[];app.report_callback_exception=lambda *error:errors.append(str(error));jobs=WriterJobs()
        try:
            for name,palette,width in (('light',LIGHT,1100),('dark',DARK,1100),('narrow',DARK,560)):
                app.geometry(f'{width}x780+40+40')
                with patch('native_chat.bootstrap_python',return_value=python):ui_runtime=ToolRuntime(fixture,{})
                panel=show_workspace(app,fixture,palette,jobs=jobs,runtime=ui_runtime);app.update()
                for tab in ('Knowledge','Connections','Workflows','Computer'):
                    panel.page(tab);app.update();capture_window(app,artifacts.path('workspace-'+name+'-'+tab.lower()+'.png'))
                panel.close();app.update()
            assert not errors,errors;passed('Native Workspace four surfaces, light/dark/narrow, no Tk callback errors')
        finally:jobs.close();jobs.wait(5);finish_tk_fixture(app)
    report['passed']=True;artifacts.path('workspace-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))


if __name__=='__main__':raise SystemExit(main())
