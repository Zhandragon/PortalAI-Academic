"""Load only the SSD's pinned, platform-specific browser/PDF dependencies."""
from pathlib import Path
import hashlib
import json
import os
import platform
import stat
import shutil
import shlex
import subprocess
import sys
import zipfile
from instance_runtime import locked
from instance_runtime import atomic

ROOT = Path(__file__).resolve().parents[1]

def platform_id():
    if sys.platform == 'win32' and platform.machine().lower() in ('amd64','x86_64'): return 'windows-x64'
    if sys.platform.startswith('linux') and platform.machine().lower() in ('amd64','x86_64'): return 'linux-x64'
    if sys.platform == 'darwin': return 'macos-arm64' if platform.machine().lower() in ('arm64','aarch64') else 'macos-x64'
    raise RuntimeError('No portable web runtime is installed for this platform/architecture')

def _linux_native(layer, executable):
    """Relocate only owned web ELFs to the bundled loader, never host libraries."""
    system=layer/'system';lib=system/'usr/lib/x86_64-linux-gnu';loader=lib/'ld-linux-x86-64.so.2'
    patcher=system/'usr/bin/patchelf'
    paths=[str(executable.parent),str(lib),str(system/'usr/lib')]
    libraries=':'.join(paths)
    receipt=layer/'linux-relocated.json'
    current=json.loads(receipt.read_text()) if receipt.exists() else {}
    binaries=[executable,executable.parent/'chrome_crashpad_handler']
    if current.get('root')!=str(layer.resolve()):
        manifest=json.loads((layer/'linux-system-manifest.json').read_text())
        for row in manifest['files']:
            path=system/row['path']
            with path.open('rb') as f:checksum=hashlib.file_digest(f,'sha256').hexdigest()
            if checksum!=row['sha256']:raise RuntimeError('Linux web dependency checksum mismatch: '+row['path'])
        loader.chmod(0o755);patcher.chmod(0o755)
        proofs=[]
        for binary in binaries:
            temp=binary.with_name(binary.name+'.relocating')
            try:
                shutil.copy2(binary,temp)
                subprocess.run([str(loader),'--library-path',libraries,str(patcher),
                                '--set-interpreter',str(loader),str(temp)],
                               check=True,capture_output=True,timeout=60)
                temp.chmod(0o755)
                with temp.open('rb') as f:checksum=hashlib.file_digest(f,'sha256').hexdigest()
                os.replace(temp,binary);proofs.append({'file':str(binary.relative_to(layer)),'sha256':checksum})
            finally:temp.unlink(missing_ok=True)
        atomic(receipt,{'root':str(layer.resolve()),'files':proofs})
    node=layer/'packages/playwright/driver/node'
    wrapper=layer/'run-node'
    wrapper.write_text('#!/bin/sh\nexport LD_LIBRARY_PATH='+shlex.quote(libraries)+'\nexec '+shlex.join([str(loader),'--library-path',libraries,str(node)])+' "$@"\n',encoding='utf-8')
    wrapper.chmod(0o755)
    os.environ['PLAYWRIGHT_NODEJS_PATH']=str(wrapper)
    # This runs only inside the dedicated web worker/check process. Its native
    # children inherit a matching loader/library set; the GUI environment is not changed.
    os.environ['FONTCONFIG_PATH']=str(system/'etc/fonts')
    os.environ['FONTCONFIG_SYSROOT']=str(system)

def prepare(root=ROOT, browser=False):
    layer = Path(root)/'Runtime/Web'/platform_id()
    if not (layer/'manifest.json').is_file(): raise RuntimeError('Portable web runtime missing; run the WebAgents update installer')
    packages = layer/'packages'
    os.environ['PLAYWRIGHT_NODEJS_PATH']=str(packages/'playwright/driver'/('node.exe' if sys.platform=='win32' else 'node'))
    if str(packages) not in sys.path: sys.path.insert(0, str(packages))
    if not browser: return layer
    names = {'windows-x64':'chrome-win64/chrome.exe', 'linux-x64':'chrome-linux64/chrome',
             'macos-x64':'chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing',
             'macos-arm64':'chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'}
    executable = layer/'browser'/names[platform_id()]
    with locked(layer/'extract.lock', timeout=120):
        if not executable.is_file():
            manifest = json.loads((layer/'manifest.json').read_text())
            with (layer/'browser.zip').open('rb') as f: digest = hashlib.file_digest(f,'sha256').hexdigest()
            if digest != manifest['browser']['sha256']: raise RuntimeError('Browser archive checksum mismatch')
            destination = layer/'browser'
            with zipfile.ZipFile(layer/'browser.zip') as archive:
                if archive.testzip(): raise RuntimeError('Browser archive CRC failure')
                for entry in archive.infolist():
                    path = destination/entry.filename
                    if not path.resolve().is_relative_to(destination.resolve()): raise ValueError('Unsafe browser archive path')
                    mode = entry.external_attr >> 16
                    if stat.S_ISLNK(mode):
                        target = archive.read(entry).decode('utf-8')
                        if not (path.parent/target).resolve().is_relative_to(destination.resolve()): raise ValueError('Unsafe browser link')
                        path.parent.mkdir(parents=True, exist_ok=True)
                        if not path.is_symlink(): path.symlink_to(target)
                    else:
                        archive.extract(entry, destination)
                        if os.name != 'nt' and mode & 0o111: path.chmod(0o755)
            if not executable.is_file(): raise RuntimeError('Browser extraction incomplete')
        if os.name != 'nt':
            executable.chmod(0o755)
            (packages/'playwright/driver/node').chmod(0o755)
        if sys.platform.startswith('linux'):_linux_native(layer,executable)
    return executable
