"""Install the matching native handoff patch without touching private state."""
from pathlib import Path
import argparse, hashlib, json, os, tempfile, time, zipfile

BASELINE='4637cebf54e6f748f3fae8d54300a94834b1043220c417d1894b2c1d1f040bf9'
FILES=('portalai_target.py','native_handoff.py')

def sha(data):return hashlib.sha256(data).hexdigest()

def install(root, package):
    root=Path(root).resolve();package=Path(package).resolve()
    if not (root/'app/projection_worker.py').is_file():raise ValueError('Select the existing PortalAI-Projection directory')
    for p in (root/'app',root/'Recovery',*(root/'app'/n for n in FILES)):
        if p.is_symlink() or getattr(p,'is_junction',lambda:False)():raise ValueError('Linked update paths are not supported')
    manifest=json.loads((package/'SHA256SUMS.json').read_text())
    after={n:(package/'app'/n).read_bytes() for n in FILES}
    if any(sha(data)!=manifest['app/'+n] for n,data in after.items()):raise ValueError('Patch checksum mismatch')
    before={n:(root/'app'/n).read_bytes() if (root/'app'/n).is_file() else None for n in FILES}
    if before==after:return 'Already installed; no files changed'
    if before['portalai_target.py'] is None or sha(before['portalai_target.py'])!=BASELINE:
        raise ValueError('Source differs from the reviewed baseline; merge this patch instead of overwriting newer code')
    if before['native_handoff.py'] is not None:raise ValueError('Unexpected existing handoff module; review before updating')
    backup=root/'Recovery'/('NativeHandoff-0.5.13-'+time.strftime('%Y%m%d-%H%M%S')+'-'+os.urandom(4).hex()+'.zip')
    backup.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(backup,'x',zipfile.ZIP_DEFLATED) as z:
        for n,data in before.items():
            if data is not None:z.writestr('app/'+n,data)
        z.writestr('restore.json',json.dumps({'absent':[n for n,data in before.items() if data is None],'before':{n:sha(data) for n,data in before.items() if data is not None}},indent=2))
    with zipfile.ZipFile(backup) as z:
        assert z.testzip() is None
        for n,data in before.items():
            if data is not None:assert z.read('app/'+n)==data
    def replace(path,data):
        fd,name=tempfile.mkstemp(prefix='.handoff-',dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
            os.replace(name,path)
        finally:
            if Path(name).exists():Path(name).unlink()
    changed=[]
    try:
        # Add the helper before the source that imports it.
        for n in reversed(FILES):
            replace(root/'app'/n,after[n]);changed.append(n)
            if (root/'app'/n).read_bytes()!=after[n]:raise RuntimeError('Post-install verification failed')
    except BaseException:
        for n in reversed(changed):
            path=root/'app'/n
            if before[n] is None:path.unlink()
            else:replace(path,before[n])
        raise
    return 'Installed and verified. Backup: '+str(backup)+'\nRestart Projection normally to load the update.'

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('projection',help='Existing PortalAI-Projection directory')
    parser.add_argument('--projection-stopped',action='store_true',help='Confirm that Projection has been stopped normally')
    args=parser.parse_args()
    if not args.projection_stopped:parser.error('Stop Projection normally first, then pass --projection-stopped')
    print(install(args.projection,Path(__file__).resolve().parent))
