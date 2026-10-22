"""Install pinned public GGUF data using bundled Python; no runtime/model activation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Agent'))
from runtime_policy import require_space, portable_path, atomic_json


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def regular_path(root, rel):
    path = portable_path(root, rel)
    current = root
    for part in Path(rel).parts:
        current = current / part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('Linked asset paths are not supported')
    return path


class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith('https://'):
            raise ValueError('Refusing an insecure asset redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def install(variants):
    entries = json.loads((ROOT / 'Agent/small_vision_assets.json').read_text(encoding='utf-8'))
    from academic_policy import asset_allowed
    entries = [row for row in entries if row['variant'] == 'standard' and asset_allowed(row)]
    pending = []
    for row in entries:
        p = regular_path(ROOT, row['path'])
        if p.exists():
            if p.stat().st_size != row['bytes'] or sha(p) != row['sha256']:
                raise ValueError('Existing asset differs; retained without replacement: ' + row['path'])
        else:
            pending.append(row)
    require_space(ROOT, sum(row['bytes'] for row in pending))
    opener = urllib.request.build_opener(HTTPSOnly())
    verified = []
    for row in entries:
        destination = regular_path(ROOT, row['path'])
        if row in pending:
            require_space(ROOT, row['bytes'])
            destination.parent.mkdir(parents=True, exist_ok=True)
            journal = ROOT / 'Maintenance/Imports' / (destination.name + '.download.json')
            if journal.exists():
                saved = json.loads(journal.read_text(encoding='utf-8'))
                name = saved.get('temporary', '')
                if (saved.get('sha256') != row['sha256'] or Path(name).name != name or
                    not name.startswith(destination.name + '.download-')):
                    raise ValueError('Download journal does not match the pinned asset')
                temporary = regular_path(ROOT, 'LLM/models/' + name)
            else:
                temporary = destination.with_name(destination.name + '.download-' + uuid.uuid4().hex)
                atomic_json(journal, {'sha256': row['sha256'], 'temporary': temporary.name})
            print('Downloading ' + destination.name, flush=True)
            for attempt in range(8):
                count = temporary.stat().st_size if temporary.exists() else 0
                if count == row['bytes']: break
                if count > row['bytes']: raise ValueError('Partial asset exceeds pinned size')
                headers = {'Range': 'bytes=' + str(count) + '-'} if count else {}
                try:
                    with opener.open(urllib.request.Request(row['url'], headers=headers), timeout=60) as response:
                        if not response.url.startswith('https://'): raise ValueError('Asset response is not HTTPS')
                        if count and (response.status != 206 or not response.headers.get('Content-Range', '').startswith('bytes '+str(count)+'-') or
                                      not response.headers.get('Content-Range', '').endswith('/'+str(row['bytes']))):
                            raise ValueError('Server did not acknowledge the exact resume offset')
                        with temporary.open('ab' if count else 'xb') as output:
                            try:
                                while True:
                                    chunk = response.read(4 * 1024 * 1024)
                                    if not chunk: break
                                    count += len(chunk)
                                    if count > row['bytes']: raise ValueError('Asset exceeds pinned size')
                                    output.write(chunk)
                            finally:
                                output.flush(); os.fsync(output.fileno())
                except (OSError, TimeoutError) as error:
                    print('Transfer interrupted: ' + type(error).__name__, flush=True)
                if count < row['bytes']:
                    print('Resuming verified asset transfer at byte ' + str(temporary.stat().st_size), flush=True)
                    time.sleep(1)
            if temporary.stat().st_size != row['bytes'] or sha(temporary) != row['sha256']:
                raise ValueError('Asset checksum/size verification failed; incomplete file retained')
            regular_path(ROOT, row['path'])
            # Exclusive publication; never overwrite a model placed by another writer.
            os.link(temporary, destination)
            temporary.unlink()
            journal.unlink()
        if destination.stat().st_size != row['bytes'] or sha(destination) != row['sha256']:
            raise ValueError('Published asset verification failed')
        verified.append(row)
        print('Verified ' + destination.name, flush=True)
        atomic_json(ROOT / 'Maintenance/Imports/small-vision-models.json',
                    {'verified': len(verified) == len(entries), 'assets': verified})


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variants', choices=('standard', 'uncensored', 'both'), default='both')
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    if not args.install:
        print('Use --install to download and verify the pinned public model files. No model is loaded.')
    else:
        install(('standard', 'uncensored') if args.variants == 'both' else (args.variants,))
