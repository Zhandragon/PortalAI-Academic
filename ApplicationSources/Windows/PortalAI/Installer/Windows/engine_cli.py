"""Small JSON-lines interface for the portable Windows installer."""
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.append(str(Path(__file__).resolve().parents[2] / 'Tools'))
import installer_core as core
import suite_installer as suite


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
        if request.get('mode')=='plan':
            report=core.inspect_update(request['package'],request['destination'])
            emit(kind='plan',message='Update '+str(report['from_version'])+' to '+report['to_version'],
                 report={k:v for k,v in report.items() if k!='files'})
            return 0
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
        stop = FileCancellation(request['cancel_file'])
        mode = request.get('mode','install')
        selected = request['selected']
        report = {}
        if request.get('suite'):
            token = sys.stdin.readline(4097).strip()
            if len(token) > 4096: raise ValueError('Invalid credential length')
            manifest = core.read_manifest(request['package'])
            edition = manifest['upgrade']['edition']
            install_primary = 'primary:'+edition in selected
            ordinary = [x for x in selected if ':' not in x]
            optional = [x for x in selected if x.startswith(('app:','copy:','utility:'))]
            if any(x.startswith('primary:') and x != 'primary:'+edition for x in selected):
                raise ValueError('Invalid primary edition')
            if not install_primary and not optional: raise ValueError('Select an application, installer copy, or utility')
            if mode == 'upgrade' and not install_primary: raise ValueError('Select the primary application to update it')
            destination = Path(request['destination']).parent if mode == 'upgrade' else Path(request['destination'])
            catalog = suite.resolve_catalog(suite.read_catalog(request['package']), optional, edition, 'Windows', request['package'], edition, token)
            planned = suite.plan(catalog, optional, edition, 'Windows', edition)
            suite.space_check(destination, planned['working_bytes'] + (core.plan(manifest, ordinary)[3] if install_primary else 0))
            if install_primary:
                report['application'] = core.install(request['package'], request['destination'], ordinary, stop, progress, events, mode=mode)
            def suite_progress(label, done, total):
                events(kind='progress', phase='suite', message=label, done=done, total=total)
            report['suite'] = suite.execute(catalog, optional, edition, 'Windows', request['package'], destination,
                                           primary=edition, stop=stop, progress=suite_progress, token=token,
                                           core=core, primary_components=ordinary)
            token = None
        else:
            report = core.install(request['package'], request['destination'], selected, stop, progress, events, mode=mode)
        emit(kind='complete', message='Installation verified. Open PortalAI normally. Existing accounts and settings are preserved during upgrades.', report=report)
        return 0
    except core.Cancelled as exc:
        emit(kind='paused', message=str(exc))
        return 2
    except Exception as exc:
        emit(kind='error', message=str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
