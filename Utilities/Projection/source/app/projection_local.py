"""One local Start request through the existing owned PortalAI lifecycle."""
import hashlib
import json
import sys
import uuid
from pathlib import Path

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'app'))
from host_runtime import target_valid,input_owner,resolve_target

def start_local(value):
    target=resolve_target(value)
    if not target_valid(target):raise ValueError('Select the actual PortalAI portable folder')
    import portalai_target
    portalai_target.configure(target)
    if sys.platform.startswith('linux'):
        from linux_job import prepare_delegation,preflight
        prepare_delegation();preflight()
    elif sys.platform=='darwin':
        from macos_job import preflight
        preflight()
    scope=MODULE/'state/input'/hashlib.sha256(input_owner().encode()).hexdigest()[:32]
    for p in (MODULE/'state',scope.parent,scope):
        if p.is_symlink():raise RuntimeError('Linked input scope refused')
        p.mkdir(mode=0o700,exist_ok=True)
    manager=portalai_target.Manager(target);manager.endpoint_dir=scope
    # Synchronous inside this short-lived helper, never on the Tk thread.
    # Use Start only: account recovery and root ownership stay in PortalAI.
    manager._operate('start',uuid.uuid4().hex)
    result=dict(manager.operation)
    if result.get('state')=='complete':result['message']=result['message'].replace('through the viewer','in the PortalAI window')
    return result

if __name__=='__main__':
    try:
        value=json.loads(sys.stdin.readline(32769))
        result=start_local(value['target'])
    except Exception as exc:result={'state':'failed','message':str(exc) or 'Local start failed'}
    print(json.dumps(result),flush=True)
