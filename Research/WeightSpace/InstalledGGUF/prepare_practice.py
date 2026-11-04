"""Rebuild pinned practice data; never download model weights or replace evidence."""
import argparse, hashlib, json, os, shutil, urllib.request
from pathlib import Path

LAB = Path(__file__).resolve().parent

def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-directory', type=Path)
    parser.add_argument('--download', action='store_true')
    args = parser.parse_args()
    if bool(args.source_directory) == bool(args.download):
        parser.error('Choose either --source-directory or --download')
    manifest = json.loads((LAB / 'practice-sources.json').read_text())
    target = LAB / 'practice.jsonl'
    if target.exists():
        if sha(target) != manifest['combined_sha256']:
            raise RuntimeError('Existing practice data differs; it was left untouched')
        print('Existing practice data matches the pinned campaign. No files changed.')
        return
    sources = args.source_directory or LAB / 'practice-downloads'
    if args.download:
        sources.mkdir(exist_ok=True)
        for row in manifest['sources']:
            path = sources / row['name']
            if not path.exists():
                if shutil.disk_usage(LAB).free - row['bytes'] < 80 * 1024**3:
                    raise RuntimeError('Practice download would violate the 80 GiB reserve')
                temporary = path.with_suffix(path.suffix + '.part')
                with urllib.request.urlopen(row['url'], timeout=45) as response, temporary.open('xb') as stream:
                    remaining = row['bytes']
                    while remaining:
                        block = response.read(min(1024**2, remaining))
                        if not block:
                            raise RuntimeError('Practice download ended early')
                        stream.write(block)
                        remaining -= len(block)
                    if response.read(1):
                        raise RuntimeError('Practice download exceeds pinned size')
                    stream.flush()
                    os.fsync(stream.fileno())
                if sha(temporary) != row['sha256']:
                    raise RuntimeError('Practice download checksum mismatch; partial file retained')
                temporary.rename(path)
            if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
                raise RuntimeError('Pinned source differs: ' + row['name'])
    for row in manifest['sources']:
        path = sources / row['name']
        if path.stat().st_size != row['bytes'] or sha(path) != row['sha256']:
            raise RuntimeError('Pinned source differs: ' + row['name'])
    if shutil.disk_usage(LAB).free - manifest['combined_bytes'] < 80 * 1024**3:
        raise RuntimeError('Practice preparation would violate the 80 GiB reserve')
    temporary = target.with_suffix('.jsonl.part')
    newline = manifest['combined_newline']
    if newline not in ('\n', '\r\n'):
        raise ValueError('Unsupported pinned newline convention')
    with temporary.open('x', encoding='utf-8', newline=newline) as output:
        for row in manifest['sources']:
            with (sources / row['name']).open(encoding='utf-8') as source:
                for line in source:
                    if line.strip():
                        output.write(json.dumps(json.loads(line), ensure_ascii=False) + '\n')
        output.flush()
        os.fsync(output.fileno())
    if temporary.stat().st_size != manifest['combined_bytes'] or sha(temporary) != manifest['combined_sha256']:
        raise RuntimeError('Combined practice data mismatch; partial file retained')
    temporary.rename(target)
    print('Pinned practice data prepared. No models downloaded; no experiment started.')

if __name__ == '__main__':
    main()
