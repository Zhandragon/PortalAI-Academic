"""Local owned read-only v2 probe. Prints safe counts/timings, never state or keys."""
import sys
from pathlib import Path as _PortablePath
sys.path.insert(0,str(_PortablePath(__file__).resolve().parents[1]/'app'))
from host_runtime import default_target
from pathlib import Path
import argparse
import hashlib
import json
import sys
import time

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'app'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=default_target())
    parser.add_argument('--samples',type=int,choices=range(1,21),default=1)
    args=parser.parse_args()
    from host_runtime import input_owner,package_paths
    sys.path[:0]=package_paths()
    import portalai_target
    root=args.root.resolve(); portalai_target.configure(root)
    from native_state_client import NativeStateClient
    manager=portalai_target.Manager(root)
    manager.endpoint_dir=MODULE/'state/input'/hashlib.sha256(input_owner().encode()).hexdigest()[:32]
    start=time.perf_counter(); client=NativeStateClient(manager); handshake=client.bind()
    bind_ms=round(1000*(time.perf_counter()-start),1)
    # Validate using the installed first-party schema, never infer a live pass
    # merely from an HTTP 200 or the presence of a listening endpoint.
    sys.path.insert(0,str(root/'ControlCenter'))
    from native_ui_protocol import validate_envelope
    from native_transport import wire_snapshot
    timings=[]
    for _ in range(args.samples):
        before=time.perf_counter(); value=client.snapshot(); validate_envelope(value)
        wire_snapshot(value['snapshot'],0)
        timings.append(round(1000*(time.perf_counter()-before),2))
    state=value['snapshot']; chat=state.get('chat',{})
    print(json.dumps({'protocol':value['protocol'],'account_state':state['account']['state'],
        'capabilities':handshake['capabilities'],'revision':state['revision'],
        'models':len(state.get('models',[])),'packages':len(state.get('packages',[])),
        'messages':len(chat.get('messages',[])),'elapsed_ms':round(1000*(time.perf_counter()-start),1),
        'bind_ms':bind_ms,'owned_read_ms':timings,
        'receiver_schema_validated':True,'private_values_printed':False,'effects_performed':False}))


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'ready':False,'error_type':type(exc).__name__,'note':'Native read-only GUI not ready; no effect or retry was performed.'}))
        raise SystemExit(1)
