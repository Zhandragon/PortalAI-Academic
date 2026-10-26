"""Authenticated local no-effect probe; never persists the loopback token.

The intentionally unsupported event cannot click, type, submit chat or change
layout. HTTP 400 is expected; the error and timing identify queue starvation.
No connection vault or HA credentials are opened by this diagnostic.
"""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
from pathlib import Path
import argparse
import http.client
import json
import sys
import time
import uuid

MODULE=Path(__file__).resolve().parents[1]
ROOT=default_target()
sys.path[:0]=[str(MODULE/'app'),str(ROOT/'Agent')]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--count',type=int,default=8)
    args=parser.parse_args()
    if not 1<=args.count<=30:parser.error('count must be 1..30')
    import portalai_target
    portalai_target.configure(ROOT);manager=portalai_target.Manager(ROOT)
    rows={p:r for p,r in manager.inventory(True).items() if portalai_target.gui_row(ROOT,r)}
    candidates=[]
    for window in manager.desktop.windows(rows):
        window['executable']=rows[window['pid']]['executable']
        manager.desktop.validate(window)
        scopes=list((MODULE/'state/input').glob('*/gui-'+str(window['pid'])+'.json'))
        if len(scopes)!=1:continue
        manager.endpoint_dir=scopes[0].parent
        endpoint=manager.endpoint(window)
        if endpoint['hwnd']==window['hwnd']:candidates.append((window,endpoint))
    if len(candidates)!=1:raise RuntimeError('Exactly one verified adapted PortalAI main window is required')
    window,endpoint=candidates[0]
    for index in range(args.count):
        manager.desktop.validate(window)
        conn=http.client.HTTPConnection('127.0.0.1',endpoint['port'],timeout=7)
        start=time.perf_counter()
        try:
            body={'hwnd':window['hwnd'],'event':{'kind':'projection_diagnostic_noop'},'request_id':uuid.uuid4().hex}
            conn.request('POST','/input',json.dumps(body),{'Authorization':'Bearer '+endpoint['token'],'Content-Type':'application/json'})
            response=conn.getresponse();result=json.loads(response.read(4097))
            print(json.dumps({'probe':index,'elapsed_ms':round(1000*(time.perf_counter()-start),1),
                              'status':response.status,'error':result.get('error'),'timing_ms':result.get('timing_ms')}),flush=True)
        finally:conn.close()
        time.sleep(.65)


if __name__=='__main__':main()
