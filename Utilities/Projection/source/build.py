"""Rebuild only the Projection downloaders from their pinned packaging metadata."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess


def render(template, values):
    for key, value in values.items():
        template = template.replace('@' + key + '@', str(value))
    return template


def build(root, source_base=None, output=None):
    source = root / 'source'
    output = output or root
    output.mkdir(parents=True, exist_ok=True)
    metadata = json.loads((root / 'PACKAGING.json').read_bytes())
    names = []
    for platform, package in metadata['packages'].items():
        url = (source_base or metadata['source_base_url']).rstrip('/') + '/' + package['path']
        values = {'SOURCE': url, 'ARCHIVE': package['archive'], 'ARCHIVE_HASH': package['sha256'],
                  'DOWNLOAD_MB': (package['bytes'] + 999_999) // 1_000_000}
        if platform == 'Windows':
            def items(rows):
                return ',\n'.join('new Item(%s, %dL, %s)' % (json.dumps(p['name']), p['bytes'], json.dumps(p['sha256'])) for p in rows)
            values.update(PARTS=items(package['parts']), FILES=items(package['files']))
            generated = output / 'Projection.generated.cs'
            generated.write_text(render((source / 'Bootstrapper.cs.in').read_text(), values), encoding='utf-8')
            exe = output / 'PortalAI-Projection-Windows-Setup.exe'
            csc = Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            command = [str(csc), '/nologo', '/target:winexe', '/optimize+', '/platform:anycpu', '/out:' + str(exe),
                       '/r:System.Windows.Forms.dll', '/r:System.Drawing.dll', '/r:System.IO.Compression.dll', '/r:System.IO.Compression.FileSystem.dll', str(generated)]
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)
            generated.unlink()
            names.append(exe.name)
        else:
            def rows(items):
                return '\n'.join('%s|%d|%s' % (p['name'], p['bytes'], p['sha256']) for p in items)
            values.update(TOP=package['top_folder'], PLATFORM=platform, PART_ROWS=rows(package['parts']), FILE_ROWS=rows(package['files']),
                          PROTOCOL='=https' if url.startswith('https://') else '=http',
                          PLATFORM_CHECK='''    [ "$(uname -s)" = Linux ] || { echo 'Projection requires Linux.' >&2; exit 2; }
    case "$(uname -m)" in x86_64|amd64) ;; *) echo 'Projection requires Linux x86-64.' >&2; exit 2 ;; esac''',
                          LAUNCH='sh "$PACKAGE/PortalAI-Projection/Start Projection.sh"')
            name = 'PortalAI-Projection-Linux-Setup.sh'
            (output / name).write_bytes(render((source / 'native.sh.in').read_text(), values).encode('utf-8'))
            names.append(name)
    results = []
    for name in names:
        path = output / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        (output / (name + '.sha256')).write_text(digest + '  ' + name + '\n', encoding='utf-8')
        results.append({'name': name, 'bytes': path.stat().st_size, 'sha256': digest})
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--source-base-url', help='Only override for a different deployment or local validation')
    parser.add_argument('--output', type=Path, help='Separate output directory for test downloaders')
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.source_base_url, args.output), indent=2))
