"""Use the same reviewed update engine for Linux and macOS staged installers."""
from pathlib import Path
import argparse,json,os,stat,sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import portable_update as update

def manifest(source,contract):
    files=[]
    for current,dirs,names in os.walk(source,followlinks=False):
        def allowed(p):
            rel=p.relative_to(source).as_posix()
            try:update.public(rel);update.path(source,rel);return True
            except update.UpdateError:return False
        dirs[:]=[d for d in dirs if allowed(Path(current)/d)]
        for name in names:
            p=Path(current)/name
            if not allowed(p):continue
            files.append({'path':p.relative_to(source).as_posix(),'bytes':p.stat().st_size,
                          'sha256':update.sha(p),'mode':stat.S_IMODE(p.stat().st_mode)&0o777})
    return {**contract,'kind':'portalai-public-update','files':files}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source',type=Path,required=True);ap.add_argument('--target',type=Path,required=True)
    ap.add_argument('--contract',type=Path,required=True);ap.add_argument('--apply',action='store_true');ap.add_argument('--recover',action='store_true')
    a=ap.parse_args();update.path(a.source,'Agent');update.path(a.target,'Agent')
    source=a.source.resolve();target=a.target.resolve();contract=update.read_json(a.contract)
    if a.apply:update.merge_executable_recovery(source,target)
    data=manifest(source,contract)
    if a.recover:
        with update.closed_guard(target,source):update.restore(target,update.read_json(update.path(target,update.PENDING)))
        result={'recovered':True}
    elif a.apply:result=update.apply(source,target,data)
    else:
        result=update.plan(source,target,data)
        result={k:v for k,v in result.items() if k!='files'}
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,update.UpdateError) as e:print('PortalAI update: '+str(e),file=sys.stderr);raise SystemExit(2)
