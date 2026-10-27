"""Optional suite assembly with pinned downloads and independent applications.

No accounts are created, no utility is started, and no saved connections are read.
GitHub credentials, when supplied, remain in memory and are stripped on redirects.
"""
from pathlib import Path, PurePosixPath
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import urllib.parse
import urllib.request
import uuid
import zipfile
import time

GIB = 1024 ** 3


class SuiteError(RuntimeError):
    pass


def check(value, message):
    if not value:
        raise SuiteError(message)


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def native(path):
    path = Path(path).absolute()
    if os.name == 'nt' and not str(path).startswith('\\\\?\\'):
        value = str(path)
        return Path('\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\') else '\\\\?\\' + value)
    return path


def relative(name):
    check(isinstance(name, str) and name and '\\' not in name and ':' not in name, 'Invalid suite path')
    p = PurePosixPath(name)
    check(not p.is_absolute() and all(x not in ('', '.', '..') for x in name.split('/')), 'Unsafe suite path')
    return p


def path_under(root, name):
    root = native(root)
    target = root.joinpath(*relative(name).parts)
    for p in (*reversed(target.parents), target):
        if p.exists() or p.is_symlink():
            st = p.lstat()
            check(not p.is_symlink() and not getattr(st, 'st_file_attributes', 0) & 0x400,
                  'Linked suite paths are not supported')
            if p.is_file():
                check(st.st_nlink == 1, 'Hardlinked suite files are not supported')
    check(target.resolve().is_relative_to(root.resolve()), 'Suite path escaped its destination')
    return target


def read_catalog(package):
    package = Path(package)
    candidates = (package/'suite-catalog.json', package/'Maintenance/Imports/suite-catalog.json')
    file = next((p for p in candidates if p.is_file()), None)
    check(file is not None, 'The suite download catalog is missing')
    catalog = json.loads(file.read_text(encoding='utf-8-sig'))
    check(catalog.get('schema') == 1 and isinstance(catalog.get('assets'), list), 'Unsupported suite catalog')
    ids = set()
    for row in catalog['assets']:
        check(row['id'] not in ids, 'Duplicate suite asset'); ids.add(row['id'])
        check(row.get('kind') in ('installer', 'utility', 'utility-installer'), 'Unknown suite asset kind')
        check(row.get('edition') in ('Full', 'Academic', 'Any'), 'Unknown suite edition')
        check(row.get('platform') in ('Windows', 'Linux', 'Mac'), 'Unknown suite platform')
        check(type(row.get('bytes')) is int and row['bytes'] > 0, 'Missing suite byte-size pin')
        check(re.fullmatch('[0-9a-f]{64}', row.get('sha256', '')), 'Missing suite SHA-256 pin')
        check(len(relative(row['file']).parts) == 1, 'Asset filename must be a basename')
        check(type(row.get('expanded_bytes')) is int and row['expanded_bytes'] >= 0, 'Missing suite storage estimate')
    return catalog


def resolve_catalog(catalog, selected, edition, platform, package, primary=None, token=None, opener=None):
    """Resolve this release's installer pins without circular archive hashes.

    A build emits a neighboring catalog after all archives exist. Online recipients
    use the publisher's exact GitHub release and its mandatory SHA-256 asset digest.
    Old installer pins are never silently substituted for the requested release.
    """
    result = json.loads(json.dumps(catalog))
    wanted = {r['asset']['id'] for r in plan(catalog, selected, edition, platform, primary)['rows']}
    sidecar = Path(package).parent/'suite-release-catalog.json'
    local = json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.is_file() else {}
    local_rows = {a['id']: a for a in local.get('assets', [])} if local.get('catalog_version') == catalog['catalog_version'] else {}
    releases = {}
    for asset in result['assets']:
        if asset['id'] not in wanted or not asset.get('resolve_release'):
            continue
        pin = local_rows.get(asset['id'])
        if pin is not None:
            check(all(pin.get(k) == asset.get(k) for k in ('id','edition','platform','file','repository','tag')), 'Suite release catalog identity mismatch')
            check(re.fullmatch('[0-9a-f]{64}', pin.get('sha256','')) and type(pin.get('bytes')) is int and pin['bytes'] > 0, 'Invalid suite release pin')
            asset.update(bytes=pin['bytes'], sha256=pin['sha256'], resolve_release=False)
            continue
        repository, tag = asset['repository'], asset['tag']
        check(repository in ('Zhandragon/PortalAI', 'Zhandragon/PortalAI-Academic'), 'Unexpected suite publisher')
        key = repository, tag
        if key not in releases:
            headers = {'User-Agent':'PortalAI-Suite/1', 'Accept':'application/vnd.github+json'}
            if asset.get('private'):
                check(token, 'This selection needs access to the private Full release. Supply a GitHub token or the offline suite release catalog and archives.')
                headers['Authorization'] = 'Bearer ' + token
            url = 'https://api.github.com/repos/' + repository + '/releases/tags/' + urllib.parse.quote(tag, safe='')
            try:
                with (opener or urllib.request.build_opener(SafeRedirect())).open(urllib.request.Request(url, headers=headers), timeout=30) as response:
                    raw = response.read(2*1024**2+1)
                    check(len(raw) <= 2*1024**2, 'Release metadata is too large')
                    releases[key] = json.loads(raw)
            except SuiteError:
                raise
            except Exception as exc:
                raise SuiteError('The requested suite release is not available (' + type(exc).__name__ + '). Use the matching offline catalog and archives, or retry after publication.') from None
        matches = [a for a in releases[key].get('assets',[]) if a.get('name') == asset['file']]
        check(len(matches) == 1, 'The requested installer is missing from the release')
        item = matches[0]; digest = item.get('digest','')
        check(re.fullmatch('sha256:[0-9a-f]{64}', digest) and type(item.get('size')) is int and item['size'] > 0, 'Publisher did not supply a verifiable installer digest')
        asset.update(bytes=item['size'], sha256=digest[7:], api_url=item['url'], url=item['browser_download_url'], resolve_release=False)
    return result


def choices(catalog, edition, platform, primary=None):
    check(edition in ('Full', 'Academic') and platform in ('Windows', 'Linux', 'Mac'), 'Invalid suite host')
    rows = []
    for asset in catalog['assets']:
        if edition == 'Academic' and asset['edition'] == 'Full':
            continue
        if asset['kind'] == 'installer':
            title = asset['edition'] + ' ' + asset['platform']
            rows.append({'id': 'copy:' + asset['id'], 'action': 'copy', 'asset': asset,
                         'label': 'Keep ' + title + ' installer copy'})
            if asset['platform'] == platform and asset['edition'] != primary:
                rows.append({'id': 'app:' + asset['edition'], 'action': 'application', 'asset': asset,
                             'label': 'Install PortalAI ' + asset['edition'] + ' for ' + platform})
        elif asset['platform'] == platform:
            title = 'PortalAI Abliterator' if asset['utility'] == 'abliterator' else 'PortalAI Home Assistant Projection'
            rows.append({'id': 'utility:' + asset['id'], 'action': 'utility', 'asset': asset, 'label': title})
    return rows


def plan(catalog, selected, edition, platform, primary=None):
    available = {r['id']: r for r in choices(catalog, edition, platform, primary)}
    check(isinstance(selected, (list, tuple)) and len(set(selected)) == len(selected), 'Duplicate suite selection')
    check(set(selected) <= set(available), 'Unavailable suite selection or edition boundary violation')
    rows = [available[x] for x in selected]
    assets = {r['asset']['sha256']: r['asset'] for r in rows}
    download = sum(a['bytes'] for a in assets.values())
    installed = 0
    for row in rows:
        asset = row['asset']
        installed += asset['bytes'] if row['action'] == 'copy' else asset['expanded_bytes']
        if row['action'] != 'copy':
            download += asset.get('additional_download_bytes', 0)
    # Retain verified downloads and leave enough space for staged publication.
    return {'rows': rows, 'download_bytes': download, 'installed_bytes': installed,
            'working_bytes': download + installed * 2, 'requires_auth': any(a.get('private') for a in assets.values())}


def space_check(destination, needed):
    parent = Path(destination).absolute()
    while not parent.exists():
        check(parent != parent.parent, 'Destination volume is missing'); parent = parent.parent
    usage = shutil.disk_usage(parent)
    reserve = max(GIB, int(usage.total * .10))
    check(usage.free >= needed + reserve,
          f'Selected suite needs {needed/GIB:.2f} GiB plus {reserve/GIB:.2f} GiB free-space reserve; '
          f'{usage.free/GIB:.2f} GiB is available. Select fewer downloads or another destination.')
    return {'required_bytes': needed, 'reserve_bytes': reserve, 'available_bytes': usage.free}


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, target):
        url = urllib.parse.urlsplit(target)
        check(url.scheme == 'https' and url.hostname and not url.username and not url.password,
              'Refusing an unsafe download redirect')
        redirected = super().redirect_request(request, fp, code, message, headers, target)
        for mapping in (redirected.headers, redirected.unredirected_hdrs):
            for key in list(mapping):
                if key.lower() == 'authorization':
                    del mapping[key]
        return redirected


def download(asset, package, destination, stop, progress, token=None, opener=None):
    # A local, exact copy works without network or credentials, including private releases.
    for folder in (Path(package)/'SuiteAssets', Path(package), Path(package).parent, Path(package).parent/'SuiteAssets'):
        p = path_under(folder, asset['file'])
        if p.is_file() and p.stat().st_size == asset['bytes'] and sha(p) == asset['sha256']:
            return p
    cache = path_under(destination, 'Utilities/.suite-downloads')
    cache.mkdir(parents=True, exist_ok=True)
    final = path_under(cache, asset['sha256'] + '.download')
    part = path_under(cache, asset['sha256'] + '.partial')
    if final.is_file():
        check(final.stat().st_size == asset['bytes'] and sha(final) == asset['sha256'], 'Cached suite asset failed verification')
        return final
    headers = {'User-Agent': 'PortalAI-Suite/1', 'Accept-Encoding': 'identity'}
    url = asset['url']
    if asset.get('private'):
        check(token, 'A GitHub token with access is needed for this private download, or place its verified archive in SuiteAssets.')
        url = asset.get('api_url', '')
        parsed = urllib.parse.urlsplit(url)
        check(parsed.scheme == 'https' and parsed.hostname == 'api.github.com' and parsed.path.startswith('/repos/'),
              'Private downloads must use the GitHub asset API')
        headers.update(Authorization='Bearer ' + token, Accept='application/octet-stream')
    parsed = urllib.parse.urlsplit(url)
    check(parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password and not parsed.fragment,
          'Suite downloads require credential-free HTTPS URLs')
    offset = part.stat().st_size if part.is_file() else 0
    check(offset <= asset['bytes'], 'Partial download exceeds the pinned size')
    if offset == asset['bytes']:
        check(sha(part) == asset['sha256'], 'Complete partial download failed verification; retain it for review')
        part.rename(final); return final
    if offset:
        headers['Range'] = 'bytes=' + str(offset) + '-'
    check(not stop.is_set(), 'Suite assembly cancelled')
    request = urllib.request.Request(url, headers=headers)
    opener = opener or urllib.request.build_opener(SafeRedirect())
    try:
        with opener.open(request, timeout=30) as response:
            if response.status == 206:
                check(response.headers.get('Content-Range') == f"bytes {offset}-{asset['bytes']-1}/{asset['bytes']}", 'Inconsistent download range')
            else:
                check(response.status == 200, 'Download did not return an archive'); offset = 0
            with part.open('ab' if offset else 'wb') as output:
                while True:
                    check(not stop.is_set(), 'Suite assembly cancelled; partial download retained')
                    block = response.read(min(1024**2, asset['bytes'] - offset + 1))
                    if not block:
                        break
                    offset += len(block)
                    check(offset <= asset['bytes'], 'Suite download exceeds pinned size')
                    output.write(block); progress(asset['id'], offset, asset['bytes'])
                output.flush(); os.fsync(output.fileno())
    except SuiteError:
        raise
    except Exception as exc:
        # Do not echo signed redirect URLs, headers, tokens, or response bodies.
        raise SuiteError('Download failed for ' + asset['id'] + ' (' + type(exc).__name__ + '). Verified and partial files were retained.') from None
    check(part.stat().st_size == asset['bytes'] and sha(part) == asset['sha256'], 'Suite archive failed size/SHA-256 verification')
    part.rename(final)
    return final


def unpack(archive, destination, asset, stop):
    """Extract pinned regular files only, preserving native permissions."""
    destination = native(destination)
    destination.mkdir(parents=True, exist_ok=False)
    seen = set(); total = 0; prefix = None
    def write(name, mode, size, source):
        nonlocal total, prefix
        check(not stop.is_set(), 'Suite assembly cancelled')
        if asset.get('strip_root'):
            top, separator, rest = name.partition('/')
            check(separator and (prefix is None or prefix == top), 'Unexpected archive root')
            prefix = top; name = rest
        relative(name)
        key = name.casefold() if os.name == 'nt' else name
        check(key not in seen, 'Duplicate archive path'); seen.add(key)
        total += size
        check(total <= asset['expanded_bytes'], 'Archive exceeds the reviewed extraction size')
        path = path_under(destination, name); path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as f:
            copied = 0
            while block := source.read(1024**2):
                check(not stop.is_set(), 'Suite assembly cancelled')
                copied += len(block); check(copied <= size, 'Archive member exceeds its stated size'); f.write(block)
            check(copied == size, 'Incomplete archive member')
        if os.name != 'nt':
            path.chmod(mode & 0o777)
    if asset['file'].endswith('.zip'):
        with zipfile.ZipFile(archive) as z:
            for item in z.infolist():
                if item.is_dir():
                    relative(item.filename.rstrip('/')); continue
                kind = (item.external_attr >> 16) & 0o170000
                check(kind in (0, stat.S_IFREG), 'Archive links and special files are refused')
                with z.open(item) as f:
                    write(item.filename, item.external_attr >> 16, item.file_size, f)
    else:
        with tarfile.open(archive, 'r|gz') as z:
            for item in z:
                if item.isdir():
                    relative(item.name.rstrip('/')); continue
                check(item.isfile(), 'Archive links and special files are refused')
                with z.extractfile(item) as f:
                    write(item.name, item.mode, item.size, f)
    return destination


def publish_tree(source, target):
    source, target = native(source), native(target)
    check(source.is_dir(), 'The selected utility is absent from its archive')
    path_under(target.parent, target.name)
    check(not target.exists(), 'An installation already exists at ' + str(target) + '. Existing accounts and utility settings are never overwritten.')
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)


def native_package(folder):
    candidates = [p.parent for p in folder.rglob('release.json') if (p.parent/'payload.zip').is_file()]
    check(len(candidates) == 1, 'Expected one native installer package')
    return candidates[0]


def execute(catalog, selected, edition, platform, package, destination, *, primary=None,
            stop=None, progress=None, token=None, core=None, primary_components=()):
    stop = stop or threading.Event(); progress = progress or (lambda *a: None)
    planned = plan(catalog, selected, edition, platform, primary)
    if not planned['rows']:
        return {'selected': [], 'verified': True}
    destination = Path(destination).absolute(); space_check(destination, planned['working_bytes'])
    reports = []
    receipt = path_under(destination, 'Utilities/suite-install-' + uuid.uuid4().hex + '.json')
    def record_result(row):
        reports.append(row)
        receipt.parent.mkdir(parents=True, exist_ok=True)
        temp = receipt.with_suffix('.partial')
        temp.write_text(json.dumps({'catalog': catalog['catalog_version'], 'completed': reports,
                                   'verified': len(reports) == len(planned['rows'])}, indent=2), encoding='utf-8')
        temp.replace(receipt)
    for row in planned['rows']:
        check(not stop.is_set(), 'Suite assembly cancelled')
        asset = row['asset']; archive = download(asset, package, destination, stop, progress, token)
        if row['action'] == 'copy':
            name = 'Utilities/Installers/' + asset['edition'] + '/' + asset['platform'] + '/' + asset['file']
            target = path_under(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                check(target.stat().st_size == asset['bytes'] and sha(target) == asset['sha256'], 'Existing installer copy differs; refusing overwrite')
            else:
                temp = target.with_name(target.name + '.' + uuid.uuid4().hex + '.partial')
                with archive.open('rb') as source, temp.open('xb') as out:
                    shutil.copyfileobj(source, out, 1024**2)
                check(sha(temp) == asset['sha256'], 'Copied installer failed verification')
                temp.rename(target)
            record_result({'id': row['id'], 'verified': True, 'path': str(target)})
            continue
        work = path_under(destination, 'Utilities/.suite-work/' + asset['id'] + '-' + uuid.uuid4().hex)
        work.mkdir(parents=True)
        extracted = unpack(archive, work/'package', asset, stop)
        if asset['kind'] == 'utility':
            # Only these public companion roots are published, never saved state.
            companion = extracted/'Utilities/PortalAI-Projection'
            check(not any((companion/n).exists() for n in ('Connections', 'state', 'Recovery')), 'Utility archive contains private state')
            targets = [(companion, destination/'Utilities/PortalAI-Projection')]
            receiver = extracted/'Utilities/PortalAI HA Setup'
            if receiver.is_dir(): targets.append((receiver, destination/'Utilities/PortalAI HA Setup'))
            for source, target in targets:
                check(source.is_dir() and not target.exists(), 'A selected utility is missing or already installed; no overwrite was attempted')
            for source, target in targets:
                publish_tree(source, target)
        elif asset['kind'] == 'utility-installer':
            check(platform == 'Windows', 'Abliterator requires its supported Windows runtime')
            import abliterator_installer_core as ablit
            pkg = native_package(extracted)
            ablit.install(pkg, work/'installed', [], stop, progress)
            publish_tree(work/'installed/Utilities/Portable Abliterator', destination/'Utilities/Portable Abliterator')
        elif platform == 'Windows':
            check(core is not None, 'The bundled Windows install engine is unavailable')
            pkg = native_package(extracted)
            manifest = core.read_manifest(pkg)
            check(manifest.get('upgrade', {}).get('edition') == asset['edition'], 'Downloaded application edition mismatch')
            ids = {c['id'] for c in manifest['components']}
            components = [x for x in primary_components if x in ids]
            core.install(pkg, work/'installed', components, stop, progress)
            publish_tree(work/'installed/PortalAI Windows', destination/('PortalAI ' + asset['edition'] + ' Windows'))
        else:
            script_name = 'install-macos.sh' if platform == 'Mac' else 'install.sh'
            scripts = list(extracted.rglob(script_name))
            scripts = [p for p in scripts if (p.parent/'payload.tar.gz').is_file()]
            check(len(scripts) == 1, 'Expected one native Unix installer')
            target = destination/('PortalAI ' + asset['edition'] + ' ' + platform)
            check(not target.exists(), 'Application destination already exists')
            env = dict(os.environ, PORTALAI_SUITE_CHILD='1')
            env.pop('PORTALAI_GITHUB_TOKEN', None)
            process = subprocess.Popen(['/bin/bash' if platform == 'Mac' else '/bin/sh', str(scripts[0]), str(target)], env=env)
            # Native installers own their safe interruption/cleanup handling.
            while process.poll() is None:
                if stop.is_set():
                    progress('Waiting for the native installer to finish safely before stopping', 0, 0)
                time.sleep(.2)
            check(process.returncode == 0 and (target/'ControlCenter/control_center_bootstrap.py').is_file(), 'Native application install did not complete')
        record_result({'id': row['id'], 'verified': True})
    return {'selected': reports, 'verified': True}


def choose_window(catalog, edition, platform, primary=None, include_primary=False):
    import tkinter as tk
    from tkinter import ttk
    window = tk.Tk(); window.title('PortalAI suite options'); window.geometry('760x650')
    body = ttk.Frame(window, padding=20); body.pack(fill='both', expand=True)
    ttk.Label(body, text='Optional installers and utilities', font=('Segoe UI', 16, 'bold')).pack(anchor='w')
    ttk.Label(body, text='Keep only what you need. Utilities remain separate programs. Installer copies for other operating systems are downloaded, not run here.', wraplength=700).pack(fill='x', pady=12)
    rows = choices(catalog, edition, platform, primary); values = {}
    total = tk.StringVar(); token = tk.StringVar(); result = []
    def changed():
        selected = [key for key, value in values.items() if value.get()]
        p = plan(catalog, [x for x in selected if not x.startswith('primary:')], edition, platform, primary)
        total.set(f"Downloads: {p['download_bytes']/GIB:.2f} GiB   |   Working disk space: {p['working_bytes']/GIB:.2f} GiB + free-space reserve")
    if include_primary:
        value = tk.BooleanVar(value=True); values['primary:'+primary] = value
        ttk.Checkbutton(body, text='Install PortalAI ' + primary + ' for ' + platform, variable=value, command=changed).pack(anchor='w', pady=8)
    for row in rows:
        value = tk.BooleanVar(); values[row['id']] = value
        size = row['asset']['bytes'] + (row['asset'].get('additional_download_bytes', 0) if row['action'] != 'copy' else 0)
        ttk.Checkbutton(body, text=row['label'] + f'  ({size/GIB:.2f} GiB download)', variable=value, command=changed).pack(anchor='w', pady=3)
    ttk.Label(body, textvariable=total, wraplength=700).pack(fill='x', pady=12)
    ttk.Label(body, text='Optional GitHub token for private downloads (kept only in memory):').pack(anchor='w')
    ttk.Entry(body, textvariable=token, show='*').pack(fill='x', pady=6)
    buttons = ttk.Frame(body); buttons.pack(side='bottom', fill='x')
    def accept():
        result.append(([key for key, value in values.items() if value.get()], token.get().strip()))
        token.set(''); window.destroy()
    def cancel():
        token.set(''); window.destroy()
    ttk.Button(buttons, text='Continue', command=accept).pack(side='right')
    ttk.Button(buttons, text='Cancel', command=cancel).pack(side='right', padx=8)
    window.protocol('WM_DELETE_WINDOW', cancel); changed(); window.mainloop()
    return result[0] if result else None


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--package', required=True, type=Path)
    ap.add_argument('--destination', required=True, type=Path)
    ap.add_argument('--edition', choices=('Full', 'Academic'))
    ap.add_argument('--platform', required=True, choices=('Windows', 'Linux', 'Mac'))
    ap.add_argument('--primary', choices=('Full', 'Academic'))
    ap.add_argument('--select', nargs='*', default=None)
    ap.add_argument('--native-driver', type=Path)
    ap.add_argument('--native-target', type=Path)
    args = ap.parse_args(); catalog = read_catalog(args.package)
    if args.native_driver:
        policy = json.loads((args.package/'upgrade.json').read_text())
        args.edition = args.primary = policy['edition']
    check(args.edition in ('Full','Academic'), 'Installer edition is missing')
    if args.select is None:
        choice = choose_window(catalog, args.edition, args.platform, args.primary, bool(args.native_driver))
        if choice is None: return 2
        selected, token = choice
    else:
        selected, token = args.select, os.environ.get('PORTALAI_GITHUB_TOKEN')
    install_primary = 'primary:'+str(args.primary) in selected
    selected = [x for x in selected if not x.startswith('primary:')]
    catalog = resolve_catalog(catalog, selected, args.edition, args.platform, args.package, args.primary, token)
    planned = plan(catalog, selected, args.edition, args.platform, args.primary)
    if planned['rows']: space_check(args.destination, planned['working_bytes'])
    if args.native_driver and install_primary:
        check(args.native_target is not None, 'Native destination is missing')
        env = dict(os.environ, PORTALAI_SUITE_CHILD='1'); env.pop('PORTALAI_GITHUB_TOKEN',None)
        code = subprocess.call(['/bin/bash' if args.platform == 'Mac' else '/bin/sh', str(args.native_driver.resolve()), str(args.native_target)], env=env)
        check(code == 0, 'Primary application installation did not complete; optional suite work was not started')
    core = None
    if args.platform == 'Windows':
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'Installer/Windows'))
        import installer_core as core
    execute(catalog, selected, args.edition, args.platform, args.package, args.destination,
            primary=args.primary, token=token, core=core, progress=lambda label, done, total: print(label + ': ' + str(done) + '/' + str(total), flush=True))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except SuiteError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
