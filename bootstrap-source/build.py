"""Build the three online installers using Python's standard library and Windows csc.

Run from a Windows build host with .NET Framework 4.x:
    python bootstrap-source/build.py
Recipients do not need Python. Metadata and templates live in this repository.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import plistlib
import subprocess
import zipfile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def render(text, values):
    for key, value in values.items():
        text = text.replace('@' + key + '@', str(value))
    return text


def build(root, source_base=None, compiler=None):
    source = root / 'bootstrap-source'
    metadata = json.loads((root / 'PACKAGING.json').read_bytes())
    base = source_base or metadata['source_base_url']
    names = []
    for platform, package in metadata['packages'].items():
        url = base.rstrip('/') + ('/' + package['path'] if package['path'] else '')
        values = {'SOURCE': url, 'ARCHIVE': package['archive'], 'ARCHIVE_HASH': package['sha256'], 'ARCHIVE_MB': (package['bytes']+999999)//1000000}
        budget = package['storage_preflight']
        values.update({k.upper(): v for k, v in budget.items() if isinstance(v, int)})
        if platform == 'Windows':
            def items(rows):
                return ',\n'.join('new Item(%s, %dL, %s)' % (json.dumps(p['name']), p['bytes'], json.dumps(p['sha256'])) for p in rows)
            values.update(PARTS=items(package['parts']), FILES=items(package['files']))
            generated = source / 'Bootstrapper.generated.cs'
            generated.write_text(render((source / 'Bootstrapper.cs.in').read_text(encoding='utf-8'), values), encoding='utf-8', newline='\n')
            exe = root / 'PortalAI-Academic-Windows-Setup.exe'
            csc = compiler or Path(os.environ['SystemRoot']) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
            command = [str(csc), '/nologo', '/target:winexe', '/optimize+', '/platform:anycpu', '/out:' + str(exe),
                       '/r:System.Windows.Forms.dll', '/r:System.Drawing.dll', '/r:System.Web.Extensions.dll', '/r:System.IO.Compression.dll', '/r:System.IO.Compression.FileSystem.dll', str(generated)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            names.append(exe.name)
        else:
            def rows(items):
                return '\n'.join('%s|%d|%s' % (p['name'], p['bytes'], p['sha256']) for p in items)
            values.update(TOP=package['top_folder'], PLATFORM=platform, PART_ROWS=rows(package['parts']), FILE_ROWS=rows(package['files']), PROTOCOL='=https' if url.startswith('https://') else '=http')
            if platform == 'Linux':
                values['PLATFORM_CHECK'] = '''    [ "$(uname -s)" = Linux ] || { echo 'This installer requires Linux.' >&2; exit 2; }
    case "$(uname -m)" in x86_64|amd64) ;; *) echo 'This installer requires Linux x86-64.' >&2; exit 2 ;; esac'''
                values['LAUNCH'] = 'sh "$PACKAGE/install.sh" "$SETUP/PortalAI Academic Linux"'
            else:
                values['PLATFORM_CHECK'] = '''    [ "$(uname -s)" = Darwin ] || { echo 'This installer requires macOS.' >&2; exit 2; }
    case "$(uname -m)" in arm64|x86_64) ;; *) echo 'This installer requires an Apple silicon or Intel Mac.' >&2; exit 2 ;; esac'''
                values['LAUNCH'] = 'bash "$PACKAGE/install-macos.sh" "$SETUP/PortalAI Academic Mac"'
            script = render((source / 'native.sh.in').read_text(encoding='utf-8'), values).encode()
            if platform == 'Linux':
                path = root / 'PortalAI-Academic-Linux-Setup.sh'
                path.write_bytes(script)
                names.append(path.name)
            else:
                # ZIP preserves the executable bit for the Mac app's shell entry.
                launcher = b'''#!/bin/bash
set -eu
HERE="$(cd "$(dirname "$0")" && pwd -P)"
if [ "$#" -gt 0 ]; then exec /bin/bash "$HERE/bootstrap.sh" "$@"; fi
exec /usr/bin/osascript - "$HERE/bootstrap.sh" <<'APPLESCRIPT'
on run argv
    set installerPath to item 1 of argv
    tell application "Terminal"
        activate
        do script "/bin/bash " & quoted form of installerPath
    end tell
end run
APPLESCRIPT
'''
                plist = plistlib.dumps({'CFBundleIdentifier': 'ai.portalai.academic.installer', 'CFBundleName': 'PortalAI Academic Installer', 'CFBundleDisplayName': 'PortalAI Academic Installer', 'CFBundleExecutable': 'installer', 'CFBundlePackageType': 'APPL', 'CFBundleVersion': '20261024.11', 'CFBundleShortVersionString': '1.0', 'LSMinimumSystemVersion': '11.0', 'LSUIElement': True})
                path = root / 'PortalAI-Academic-Mac-Setup.zip'
                with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
                    for name, data, mode in [('Contents/Info.plist', plist, 0o644), ('Contents/MacOS/installer', launcher, 0o755), ('Contents/MacOS/bootstrap.sh', script, 0o755)]:
                        info = zipfile.ZipInfo('PortalAI Academic Installer.app/' + name, date_time=(2026, 10, 21, 0, 0, 0))
                        info.create_system = 3
                        info.external_attr = (0o100000 | mode) << 16
                        info.compress_type = zipfile.ZIP_DEFLATED
                        archive.writestr(info, data)
                names.append(path.name)
    for name in names:
        (root / (name + '.sha256')).write_text(f'{sha(root / name)}  {name}\n', encoding='utf-8', newline='\n')
    files = sorted(p for p in root.rglob('*') if p.is_file() and p != root / 'SHA256SUMS' and p != root / 'InstallerSources/Windows/release.json' and '.git' not in p.relative_to(root).parts and '__pycache__' not in p.relative_to(root).parts)
    (root / 'SHA256SUMS').write_text(''.join(f'{sha(p)}  {p.relative_to(root).as_posix()}\n' for p in files), encoding='utf-8', newline='\n')
    return [{'name': n, 'bytes': (root / n).stat().st_size, 'sha256': sha(root / n)} for n in names]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--source-base-url', help='Override only for a different deployment or local testing; rebuilds all download URLs.')
    args = parser.parse_args()
    print(json.dumps(build(args.root, args.source_base_url), indent=2))
