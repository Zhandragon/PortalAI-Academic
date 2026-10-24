"""Small JSON-lines interface for the portable Windows installer."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import installer_core as core


class FileCancellation:
    def __init__(self, path):
        self.path = Path(path)

    def is_set(self):
        return self.path.exists()


def emit(**message):
    print(json.dumps(message), flush=True)


def main():
    if len(sys.argv) == 2 and sys.argv[1] == '--selfcheck':
        emit(kind='selfcheck', python=sys.version.split()[0], sha256=True, ssl=True)
        return 0
    if len(sys.argv) != 2:
        emit(kind='error', message='The installer request is missing.')
        return 1
    try:
        request = json.loads(Path(sys.argv[1]).read_text('utf-8-sig'))
        last=[0.0];state=[None]
        def progress(label,done,total):
            # Detailed byte updates use structured events, never repeated log rows.
            if total==0 and label!=state[0]:
                state[0]=label;emit(kind='log',message=label)
        def events(**message):
            now=time.monotonic();key=(message.get('phase'),message.get('message'))
            changed=key!=getattr(events,'key',None)
            if changed or now-last[0]>.15 or (message.get('total',0)>0 and message.get('done')==message.get('total')):
                events.key=key;last[0]=now;emit(**message)
        report = core.install(request['package'], request['destination'], request['selected'],
                              FileCancellation(request['cancel_file']), progress, events)
        emit(kind='complete', message='Installation verified. Open PortalAI in the new folder to create your own account.', report=report)
        return 0
    except core.Cancelled as exc:
        emit(kind='paused', message=str(exc))
        return 2
    except Exception as exc:
        emit(kind='error', message=str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
