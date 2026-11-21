"""Headless, CPU-only browser-use acceptance in marked synthetic artifacts."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Tools')]


async def fixture(base):
    from browser_use_worker import BrowserSession
    session=BrowserSession(ROOT,SimpleNamespace(check=lambda:None),'admin')
    result=await session.run({'action':'open','url':'https://example.com'})
    assert 'Example Domain' in result['text'],result
    page=next(p for p in session.connection.contexts[0].pages if 'example.com' in p.url)
    await page.set_content('<!doctype html><title>PortalAI synthetic browser fixture</title><label>Name <input id="name"></label><button onclick="document.querySelector(\'output\').textContent=\'Saved \'+document.querySelector(\'input\').value">Save fixture</button><output>Not saved</output>')
    state=await session.state()
    entry=next(e for e in state['elements'] if e['role']=='textbox')
    filled=await session.run({'action':'fill','element':entry['id'],'text':'portable fixture','observation':state['observation']})
    assert await page.locator('input').input_value()=='portable fixture'
    try:await session.run({'action':'fill','element':entry['id'],'text':'stale','observation':state['observation']})
    except ValueError:pass
    else:raise AssertionError('Stale observation accepted')
    button=next(e for e in filled['elements'] if e['role']=='button')
    clicked=await session.run({'action':'click','element':button['id'],'observation':filled['observation']})
    assert 'Saved portable fixture' in clicked['text'],clicked
    first_page=session.page
    await session.run({'action':'open','url':'https://example.com/?portalai_fixture=second'})
    tabs=await session.run({'action':'tabs'})
    assert len(tabs['tabs'])>=2
    switched=await session.run({'action':'switch','page':first_page})
    assert 'Saved portable fixture' in switched['text']
    await page.set_content('<label><input type="checkbox">Confirm synthetic choice</label><a href="https://example.com/?portalai_fixture=next">Next fixture</a>')
    state=await session.state()
    box=next(e for e in state['elements'] if e['role']=='checkbox')
    checked=await session.run({'action':'press','element':box['id'],'key':'Space','observation':state['observation']})
    assert await page.locator('input').is_checked()
    link=next(e for e in checked['elements'] if e['role']=='link')
    await session.run({'action':'click','element':link['id'],'observation':checked['observation']})
    await page.wait_for_url('**portalai_fixture=next')
    await session.run({'action':'back'})
    await page.wait_for_url('https://example.com/',wait_until='commit')
    try:await session.run({'action':'open','url':'http://127.0.0.1:1/private'})
    except (ValueError,PermissionError):pass
    else:raise AssertionError('Private destination accepted')
    session.role='guest'
    try:await session.run({'action':'click','element':button['id'],'observation':clicked['observation']})
    except PermissionError:pass
    else:raise AssertionError('Guest input accepted')
    print(json.dumps({'ok':True,'public_read':True,'accessible_state':True,'fill':True,'click':True,'tabs_switch':True,'checkbox_keyboard':True,'history_back':True,'stale_rejected':True,'private_url_rejected':True,'guest_input_rejected':True,'headless':True,'synthetic':True}),flush=True)


def main():
    global ROOT
    parser=argparse.ArgumentParser();parser.add_argument('--worker',action='store_true');parser.add_argument('--artifacts-dir',required=True)
    parser.add_argument('--runtime-root',type=Path)
    args=parser.parse_args()
    if args.runtime_root:ROOT=args.runtime_root.resolve()
    from validation_artifacts import ValidationArtifacts
    artifacts=ValidationArtifacts(ROOT,Path(args.artifacts_dir));base=artifacts.path()
    if args.worker:
        try:asyncio.run(fixture(base))
        except BaseException:
            import traceback
            traceback.print_exc();sys.stdout.flush();sys.stderr.flush();os._exit(1)
        sys.stdout.flush();os._exit(0)
    from browser_use_runtime import environment
    profile=SimpleNamespace(private=lambda rel:base/rel)
    env=environment(ROOT,profile,os.environ.copy())
    from tool_process import ToolProcess
    owner=ToolProcess(ROOT,[sys.executable,'-B',str(Path(__file__).resolve()),'--worker','--artifacts-dir',str(base),'--runtime-root',str(ROOT)],cwd=base,env=env,check=lambda:None,monitor=False)
    try:
        proc=owner.start();out,err=proc.communicate(timeout=120)
        (base/'browser-acceptance.stdout').write_text(out,encoding='utf-8')
        (base/'browser-acceptance.stderr').write_text(err,encoding='utf-8')
        print(out);print(err[-3000:]);assert proc.returncode==0,proc.returncode
        assert owner.job.active(),'Browser tree should remain owned after worker exit'
        owner.close();print('Owned browser tree cancelled after successful fixture.')
    finally:owner.close()


if __name__=='__main__':main()
