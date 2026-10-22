"""Apply only the known Mac GUI projection adapter update to a closed root."""
from pathlib import Path
import argparse,hashlib,json,os,sys,time,uuid
HERE=Path(__file__).resolve().parent
PAYLOAD=HERE/'MacHostUpdate'

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def inspect(root):
    manifest=json.loads((PAYLOAD/'manifest.json').read_text())
    destination=root/'ControlCenter/remote_desktop_input.py'
    for path in (root,root/'ControlCenter',destination):
        if path.is_symlink():raise ValueError('Linked update path refused')
    current=digest(destination)
    if digest(PAYLOAD/'remote_desktop_input.py')!=manifest['after']:raise ValueError('Update payload checksum failed')
    if current==manifest['after']:return destination,manifest,False
    if current!=manifest['before']:raise ValueError('GUI adapter differs from the reviewed WebAgents build; merge this update into that version before applying')
    return destination,manifest,True

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();root=args.root.resolve()
    destination,manifest,needed=inspect(root)
    if not needed:print('Mac GUI projection update already installed.');return
    if not args.apply:print('Compatible closed-root update available. Rerun with --apply after normal PortalAI Exit.');return
    if sys.platform!='darwin':raise RuntimeError('Apply this host update on macOS')
    sys.path[:0]=[str(root/'Agent'),str(root/'ControlCenter'),str(root/'Runtime/MacPackages/gui')]
    from mission_runner import process_lock
    from instance_runtime import locked,host_directory,instance_key
    from profile_shutdown import verify_stopped,_marker
    with process_lock(root/'Private/profile-runtime.lock'),locked(host_directory()/(instance_key(root)+'.lease'),timeout=1):
        marker=_marker(root)
        if marker and marker['state']!='closed':raise RuntimeError('Finish normal profile sealing/recovery before updating')
        if not verify_stopped(root)['stopped']:raise RuntimeError('Close all owned PortalAI processes before updating')
        destination,manifest,needed=inspect(root)
        if not needed:return
        recovery=root/'Maintenance/Patches'/('MacProjection_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
        recovery.mkdir(parents=True,exist_ok=False)
        before=destination.read_bytes();(recovery/'remote_desktop_input.py.before').write_bytes(before)
        if digest(recovery/'remote_desktop_input.py.before')!=manifest['before']:raise RuntimeError('Recovery verification failed')
        data=(PAYLOAD/'remote_desktop_input.py').read_bytes()
        stage=destination.with_name(destination.name+'.mac-projection-'+uuid.uuid4().hex)
        with stage.open('xb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        if digest(destination)!=manifest['before']:raise RuntimeError('Source changed during update')
        os.replace(stage,destination)
        if digest(destination)!=manifest['after']:raise RuntimeError('Installed checksum mismatch; preserve recovery for review')
        (recovery/'manifest.json').write_text(json.dumps(manifest,indent=2))
        print('Verified Mac host adapter installed. Recovery: '+str(recovery))
        print('Launch PortalAI through Projection, then sign in normally. No account or pairing was changed.')

if __name__=='__main__':main()
