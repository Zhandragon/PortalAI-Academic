"""Private JSON-lines browser worker. EOF/Stop closes its entire owned job."""
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]

def main():
    # The parent assigns job ownership before releasing this stdin start gate.
    init=json.loads(sys.stdin.readline())
    from profile_context import CapturedProfile
    from web_capabilities import WebSession
    profile=CapturedProfile(ROOT)
    session=WebSession(ROOT,profile,init['role'])
    try:
        for line in sys.stdin:
            try:
                if len(line)>2*1024*1024:raise ValueError('Web request too large')
                request=json.loads(line);profile.check()
                result=session.run(request);profile.check()
                print(json.dumps({'ok':True,'result':result},ensure_ascii=True),flush=True)
            except Exception as exc:
                print(json.dumps({'ok':False,'error':type(exc).__name__+': '+str(exc)[:1000],
                                  'retry_safe':False},ensure_ascii=True),flush=True)
    finally:session.close()

if __name__=='__main__':main()
