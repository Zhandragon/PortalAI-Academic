"""Clean-install engine. No account creation, pairing, elevation or process control.

Only the release builder supplies the allowlisted payload and pinned asset manifest.
Downloads are retained for resume; every complete artifact is hashed before use.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import threading
import tarfile
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile


class InstallError(RuntimeError):
    pass


class Cancelled(InstallError):
    pass


# Comfy's upstream examples live in account-owned folders. Shipping even an
# empty placeholder there makes PortalAI require recovery before first setup.
COMFY_USER_ROOTS = tuple('portalai/generative/comfyui_windows_portable/comfyui/' + name
                        for name in ('input', 'output', 'temp', 'user'))


def canonical_destination(value):
    lower = value.casefold()
    if lower == 'portalai windows' or lower.startswith('portalai windows/'):
        return 'portalai' + lower[len('portalai windows'):]
    return lower


def is_comfy_user_destination(value):
    relative(value)
    lower = canonical_destination(value)
    return any(lower == root or lower.startswith(root + '/') for root in COMFY_USER_ROOTS)


def sha256(path, progress=None):
    with Path(path).open('rb') as f:
        if progress is None:return hashlib.file_digest(f, 'sha256').hexdigest()
        digest=hashlib.sha256();done=0;total=Path(path).stat().st_size
        progress(0,total)
        while block:=f.read(4*1024**2):
            digest.update(block);done+=len(block);progress(done,total)
        return digest.hexdigest()


def relative(value):
    """Reject Windows aliases, streams, traversal and ambiguous archive names."""
    if not isinstance(value, str) or not value or '\\' in value:
        raise InstallError('Invalid relative path')
    parts = value.split('/')
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{p}{i}' for p in ('COM', 'LPT') for i in range(1, 10)}
    for p in parts:
        if (p in ('', '.', '..') or p.endswith((' ', '.')) or
                any(ord(c) < 32 or c in ':*?"<>|' for c in p) or
                p.split('.')[0].upper() in reserved):
            raise InstallError('Unsafe relative path: ' + value)
    return PurePosixPath(value)


def checked_path(root, value):
    root = Path(root).absolute()
    parts = relative(value).parts
    target = root.joinpath(*parts)
    for current in [*reversed(root.parents), root, *[root.joinpath(*parts[:i]) for i in range(1, len(parts)+1)]]:
        if current.exists() or current.is_symlink():
            info = current.lstat()
            if (current.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400
                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                raise InstallError('Linked installation paths are not supported: ' + str(current))
    if not target.resolve().is_relative_to(root.resolve()):
        raise InstallError('Destination escapes installation folder')
    return target


def public_destination(value):
    relative(value)
    lower = canonical_destination(value)
    roots = ('portalai/', 'utilities/')
    if not lower.startswith(roots) and lower not in ('portalai.exe', 'portalai.sh', 'start_here.txt', 'rename portalai.cmd', 'start portalai windows.cmd', 'start portalai linux.sh', 'start portalai mac.command'):
        raise InstallError('Destination is outside the public application layout')
    protected = ('portalai/private/', 'portalai/outputs/', 'portalai/cache/',
                 'portalai/.git/', 'portalai/recovery/',
                 'utilities/portalai-projection/connections/', 'utilities/portalai-projection/state/',
                 'utilities/portalai-projection/recoveryhelper/connections/',
                 'utilities/portalai-projection/recoveryhelper/state/')
    if is_comfy_user_destination(value) or any(lower.startswith(p) or lower == p.rstrip('/') for p in protected):
        raise InstallError('Private or live-state destination refused: ' + value)
    return value


def validate_pin(item):
    if not re.fullmatch('[0-9a-f]{64}', item.get('sha256', '')):
        raise InstallError('Missing SHA-256 pin')
    if type(item.get('bytes')) is not int or item['bytes'] < 0:
        raise InstallError('Missing byte-size pin')


class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != 'https' or parsed.username or parsed.password:
            raise InstallError('Refusing a non-HTTPS redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(item, cache, stop, progress, opener=None):
    try:
        return _fetch_one(item, cache, stop, progress, opener)
    except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError) as error:
        raise InstallError(
            f"Download failed for {item['id']} from {item['url']}: {error}. "
            "HTTPS certificate verification remains enabled. For certificate errors, "
            "check the computer's date/time and certificate updates; the server or "
            "a network inspection proxy may also need its certificate renewed. "
            "Verified downloads are retained for retry.") from error


def download_artifact(item, package, cache, stop, progress):
    if 'bundled_file' not in item:
        return fetch(item, cache, stop, progress)
    validate_pin(item)
    path = checked_path(package, item['bundled_file'])
    if not path.is_file() or path.stat().st_size != item['bytes'] or sha256(path) != item['sha256']:
        raise InstallError('Bundled download is missing or failed verification: ' + item['id'])
    progress('Verified bundled download: ' + item['id'], item['bytes'], item['bytes'])
    return path


def _fetch_one(item, cache, stop, progress, opener=None):
    from academic_policy import require_asset
    require_asset(item)
    validate_pin(item)
    url = urllib.parse.urlsplit(item['url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.fragment:
        raise InstallError('Downloads require public HTTPS URLs without credentials')
    cache = Path(cache)
    checked_path(cache.parent, cache.name)
    cache.mkdir(parents=True, exist_ok=True)
    target = checked_path(cache, item['sha256'] + '.download')
    part = checked_path(cache, item['sha256'] + '.partial')
    if target.exists():
        if target.stat().st_size == item['bytes'] and sha256(target) == item['sha256']:
            return target
        target.rename(checked_path(cache, target.name + '.rejected-' + uuid.uuid4().hex[:12]))
    offset = part.stat().st_size if part.exists() else 0
    if stop.is_set():
        raise Cancelled('Paused before download')
    if item['bytes'] == 0 and not part.exists():
        part.touch(exist_ok=False)
    if offset > item['bytes'] or (part.exists() and offset == item['bytes'] and sha256(part) != item['sha256']):
        part.rename(checked_path(cache, part.name + '.rejected-' + uuid.uuid4().hex[:12]))
        offset = 0
    if offset < item['bytes']:
        headers = {'Accept-Encoding': 'identity', 'User-Agent': 'PortalAI-Clean-Installer/1'}
        if offset:
            headers['Range'] = f'bytes={offset}-'
        progress('Downloading ' + item['id'] + ' from ' + item['url'], offset, item['bytes'])
        request = urllib.request.Request(item['url'], headers=headers)
        opener = opener or urllib.request.build_opener(HTTPSOnly())
        with opener.open(request, timeout=30) as response:
            status = response.status
            if status == 206:
                if response.headers.get('Content-Range') != f"bytes {offset}-{item['bytes']-1}/{item['bytes']}":
                    raise InstallError('Server returned an inconsistent download range')
            elif status == 200:
                offset = 0
            else:
                raise InstallError('Unexpected download response: ' + str(status))
            with part.open('ab' if offset else 'wb') as output:
                while True:
                    if stop.is_set():
                        raise Cancelled('Paused. Run the installer again to resume verified downloads.')
                    block = response.read(min(4 * 1024**2, item['bytes'] - offset + 1))
                    if not block:
                        break
                    offset += len(block)
                    if offset > item['bytes']:
                        raise InstallError('Download exceeds pinned size')
                    output.write(block)
                    progress(item['id'], offset, item['bytes'])
                output.flush()
                os.fsync(output.fileno())
    if not part.exists() or part.stat().st_size != item['bytes'] or sha256(part) != item['sha256']:
        raise InstallError('Download size or checksum failed; the file was not installed. Retry to resume or replace the damaged download.')
    part.rename(target)
    return target


def write_verified(source, target, expected, stop, progress=None):
    validate_pin(expected)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + '.installing')
    if target.exists() or partial.exists():
        raise InstallError('Refusing to replace an existing installation file: ' + str(target))
    total = 0
    if progress:progress(expected,0,expected['bytes'])
    digest = hashlib.sha256()
    with partial.open('xb') as output:
        while True:
            if stop.is_set():
                raise Cancelled('Installation paused; the incomplete folder is not a finished installation')
            block = source.read(4 * 1024**2)
            if not block:
                break
            total += len(block)
            if total > expected['bytes']:
                raise InstallError('Extracted file exceeds pinned size')
            digest.update(block)
            output.write(block)
            if progress:progress(expected,total,expected['bytes'])
        output.flush()
        os.fsync(output.fileno())
    if total != expected['bytes'] or digest.hexdigest() != expected['sha256']:
        raise InstallError('Extracted file checksum mismatch: ' + str(target))
    partial.rename(target)


def extract_allowlist(archive_path, members, root, stop, progress=None):
    """Every installed member has an explicit destination, size and digest."""
    destinations = set()
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [i.filename.casefold() for i in infos]
        if len(set(names)) != len(names):
            raise InstallError('Archive has duplicate member names')
        for info in infos:
            relative(info.filename.rstrip('/'))
        for row in members:
            validate_pin(row)
            relative(row['member'])
            public_destination(row['dest'])
            if row['dest'].casefold() in destinations:
                raise InstallError('Duplicate destination')
            destinations.add(row['dest'].casefold())
            info = archive.getinfo(row['member'])
            # Unselected upstream entries are never opened or installed. Some
            # source archives include development-only symlinks; reject links
            # only when selected, without following or materializing them.
            if stat.S_ISLNK(info.external_attr >> 16):
                raise InstallError('Selected archive member is a link: ' + row['member'])
            if info.is_dir() or info.file_size != row['bytes']:
                raise InstallError('Archive member does not match pinned metadata')
            checked_path(root, row['dest'])
        for row in members:
            with archive.open(row['member']) as source:
                write_verified(source, checked_path(root, row['dest']), row, stop, progress)


def extract_tar_allowlist(archive_path, members, root, stop, progress=None):
    with tarfile.open(archive_path) as archive:
        infos = archive.getmembers()
        names = [i.name.casefold() for i in infos]
        if len(set(names)) != len(names):
            raise InstallError('Archive has duplicate member names')
        for info in infos:
            relative(info.name.rstrip('/'))
        for row in members:
            info = archive.getmember(row['member'])
            if not info.isfile() or info.size != row['bytes']:
                raise InstallError('Only explicitly pinned regular tar members can be installed')
        for row in members:
            with archive.extractfile(row['member']) as source:
                write_verified(source, checked_path(root, row['dest']), row, stop, progress)


NSIS_HELPER = 'PortalAI Windows/Tools/Archive'
NSIS_HELPER_HASHES = {
    '7z.exe': '95fff19b73eff77c87c0d7bd32822e43fb90dd2932459f962eb532d8dfb6ba53',
    '7z.dll': '899cd73d7fc60e1c1c35c7de0f5bed3dc69bfe2cecbd48014d868a347970a0b1',
}


def nsis_listing(text):
    """Validate 7-Zip's NSIS member listing before any payload extraction."""
    if len(text) > 64 * 1024**2:
        raise InstallError('NSIS inventory exceeds its size limit')
    names = {}
    for block in re.split(r'\r?\n\r?\n', text.strip('\r\n')):
        fields = {}
        for line in block.splitlines():
            key, sep, value = line.partition(' = ')
            if not sep or key in fields:
                raise InstallError('Ambiguous NSIS inventory')
            fields[key] = value
        name = fields.get('Path', '').replace('\\', '/')
        relative(name)
        if (any('link' in key.casefold() for key in fields) or
                fields.get('Folder') == '+' or 'L' in fields.get('Attributes', '')):
            raise InstallError('Only regular NSIS payload files are supported')
        if name.casefold() in names:
            raise InstallError('Duplicate NSIS member name')
        names[name.casefold()] = name
    if not names:
        raise InstallError('Empty NSIS inventory')
    return names


def iso_listing(text):
    """Validate ISO directory records, then return only regular payload files."""
    if len(text) > 64 * 1024**2:
        raise InstallError('ISO inventory exceeds its size limit')
    seen = set()
    files = []
    for block in re.split(r'\r?\n\r?\n', text.strip('\r\n')):
        fields = {}
        for line in block.splitlines():
            key, sep, value = line.partition(' = ')
            if not sep or key in fields:
                raise InstallError('Ambiguous ISO inventory')
            fields[key] = value
        name = fields.get('Path', '').replace('\\', '/')
        relative(name)
        if name.casefold() in seen:
            raise InstallError('Duplicate ISO member name')
        seen.add(name.casefold())
        # The ISO reader emits an empty Symbolic Link field for regular files.
        # Only that exact empty field is harmless; targets/unknown link fields fail.
        if any('link' in key.casefold() and (key != 'Symbolic Link' or value)
               for key, value in fields.items()) or 'L' in fields.get('Attributes', ''):
            raise InstallError('Linked ISO members are unsupported')
        if fields.get('Folder') == '+' or fields.get('Attributes', '').startswith('D'):
            continue
        files.append('\n'.join(key+' = '+value for key,value in fields.items()
                               if key != 'Symbolic Link'))
    return nsis_listing('\n\n'.join(files))


def _verified_nsis_extractor(root):
    for name, digest in NSIS_HELPER_HASHES.items():
        path = checked_path(root, NSIS_HELPER+'/'+name)
        if not path.is_file() or sha256(path) != digest:
            raise InstallError('Bundled archive reader checksum failed')
    return checked_path(root, NSIS_HELPER+'/7z.exe')


def extract_nsis_allowlist(archive_path, artifact, root, stop, progress=None):
    """Read a pinned NSIS/ISO archive; never execute an installer or boot it."""
    validate_pin(artifact)
    archive_type = {'nsis': 'NSIS', 'iso': 'Iso'}.get(artifact.get('format', 'nsis'))
    if archive_type is None:
        raise InstallError('Unsupported native archive type')
    if Path(archive_path).stat().st_size != artifact['bytes'] or sha256(archive_path) != artifact['sha256']:
        raise InstallError('NSIS archive checksum failed')
    prefix = public_destination(artifact['destination_prefix'])
    output = checked_path(root, prefix)
    if output.exists():
        raise InstallError('NSIS extraction requires a new component folder')
    extractor = _verified_nsis_extractor(root)
    if stop.is_set():
        raise Cancelled('Paused before archive extraction')
    options = dict(capture_output=True, text=True, encoding='utf-8', errors='strict',
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    result = subprocess.run([str(extractor), 'l', '-slt', '-ba', '-sccUTF-8', '-t'+archive_type, str(archive_path)], **options)
    if result.returncode:
        raise InstallError('Could not inventory the pinned NSIS archive')
    names = iso_listing(result.stdout) if archive_type == 'Iso' else nsis_listing(result.stdout)
    requested = set()
    for row in artifact['members']:
        validate_pin(row); relative(row['member']); public_destination(row['dest'])
        if row['dest'] != prefix+'/'+row['member'] or names.get(row['member'].casefold()) != row['member']:
            raise InstallError('NSIS member does not match its destination')
        if row['member'].casefold() in requested:
            raise InstallError('Duplicate requested NSIS member')
        requested.add(row['member'].casefold())
    if not requested:
        raise InstallError('No NSIS payload files selected')
    listing = checked_path(root, '.nsis-members-'+uuid.uuid4().hex+'.txt')
    with listing.open('x', encoding='utf-8', newline='\n') as f:
        f.write(''.join(row['member']+'\n' for row in artifact['members']))
    try:
        if stop.is_set():
            raise Cancelled('Paused before archive extraction')
        # -spd makes the allowlist literal; the reviewed type is forced.
        # Cancellation waits for this owned extraction to finish naturally.
        result = subprocess.run([str(extractor), 'x', '-t'+archive_type, '-spd', '-scsUTF-8',
                                 '-sccUTF-8', '-y', '-o'+str(output), '-i@'+str(listing),
                                 str(archive_path)], **options)
        if result.returncode:
            raise InstallError('NSIS extraction failed; incomplete staging was retained')
    finally:
        listing.unlink()
    found = set()
    for directory, subdirs, files in os.walk(output, followlinks=False):
        for name in subdirs+files:
            path = Path(directory)/name
            checked_path(root, path.relative_to(root).as_posix())
        for name in files:
            found.add((Path(directory)/name).relative_to(output).as_posix().casefold())
    if found != requested:
        raise InstallError('NSIS extracted inventory differs from the allowlist')
    for row in artifact['members']:
        path = checked_path(root, row['dest'])
        if path.stat().st_size != row['bytes'] or sha256(path) != row['sha256']:
            raise InstallError('NSIS file checksum failed: '+row['dest'])
        if progress:progress(row,row['bytes'],row['bytes'])
    if stop.is_set():
        raise Cancelled('Paused after verified archive extraction')


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise InstallError('Duplicate manifest key: ' + key)
        obj[key] = value
    return obj


def read_manifest(package):
    return json.loads((Path(package) / 'release.json').read_text('utf-8'), object_pairs_hook=_unique_object)


def planned_receipts(manifest, chosen, ordinary_files):
    """Plan deterministic records whose prerequisite files must pass readback."""
    ids = {c['id'] for c in manifest['components']}
    selected = {c['id'] for c in chosen}
    files = {r['dest'].casefold(): r for r in ordinary_files}
    receipts = []
    destinations = set()
    for definition in manifest.get('generated_receipts', []):
        dest = public_destination(definition['dest'])
        if not canonical_destination(dest).startswith('portalai/maintenance/imports/') or not dest.endswith('.json'):
            raise InstallError('Generated receipts must use the public import record folder')
        if dest.casefold() in destinations or dest.casefold() in files:
            raise InstallError('Receipt destination overlaps another file')
        destinations.add(dest.casefold())
        required = definition['components']
        if not required or len(set(required)) != len(required) or set(required) - ids:
            raise InstallError('Receipt references unknown or duplicate components')
        dependencies = definition['files']
        if not dependencies:
            raise InstallError('Receipt has no verified file prerequisites')
        for dependency in dependencies:
            validate_pin(dependency)
            public_destination(dependency['dest'])
        if not set(required) <= selected:
            continue
        for dependency in dependencies:
            actual = files.get(dependency['dest'].casefold())
            if actual is None or any(actual[k] != dependency[k] for k in ('bytes','sha256')):
                raise InstallError('Receipt prerequisite is missing or differs from installed payload')
        data = dict(definition['data'])
        data['verified'] = True
        content = json.dumps(data, indent=2, ensure_ascii=True, allow_nan=False)+'\n'
        encoded = content.encode('utf-8')
        if len(encoded) > 64 * 1024**2:
            raise InstallError('Generated receipt exceeds its size limit')
        receipts.append(dict(dest=dest, bytes=len(encoded), sha256=hashlib.sha256(encoded).hexdigest(),
                             receipt_utf8=content))
    return receipts


def plan(manifest, selected):
    from academic_policy import validate_installer_manifest
    validate_installer_manifest(manifest)
    if manifest.get('schema') != 1 or manifest.get('status') != 'RELEASED':
        raise InstallError('This package has not passed release acceptance')
    components = manifest['components']
    ids = [c['id'] for c in components]
    if len(ids) != len(set(ids)) or set(selected) - set(ids):
        raise InstallError('Duplicate or unknown component')
    requested = set(selected) | {c['id'] for c in components if c.get('required')}
    dependencies = {c['id']: c.get('depends_on', []) for c in components}
    for key, values in dependencies.items():
        if len(values) != len(set(values)) or set(values) - set(ids) or key in values:
            raise InstallError('Invalid component dependencies')
    # Reach a fixed point so selecting an optional feature includes its shared
    # public models. Shared destinations still appear exactly once below.
    while True:
        expanded = requested | {dep for key in requested for dep in dependencies[key]}
        if expanded == requested:
            break
        requested = expanded
    chosen = [c for c in components if c['id'] in requested]
    artifacts = [a for c in chosen for a in c.get('artifacts', [])]
    dests = set()
    expected_files = []
    for artifact in [manifest['payload'], *artifacts]:
        validate_pin(artifact)
        fmt = artifact.get('format', 'zip' if artifact is manifest['payload'] else '')
        if fmt not in ('zip', 'tar', 'file', 'nsis', 'iso'):
            raise InstallError('Unsupported pinned artifact format')
        if fmt == 'file' and len(artifact['members']) != 1:
            raise InstallError('Direct files require one destination')
        for row in artifact['members']:
            if 'receipt_utf8' in row:
                raise InstallError('Archive members cannot impersonate generated receipts')
            validate_pin(row)
            public_destination(row['dest'])
            if fmt != 'file':
                relative(row['member'])
                if fmt in ('nsis', 'iso') and row['dest'] != public_destination(artifact['destination_prefix'])+'/'+row['member']:
                    raise InstallError('NSIS destination must retain the archive layout')
            elif row['bytes'] != artifact['bytes'] or row['sha256'] != artifact['sha256']:
                raise InstallError('Direct file pin differs from artifact pin')
            dest = row['dest'].casefold()
            if dest in dests:
                raise InstallError('Release defines overlapping destinations')
            dests.add(dest)
            expected_files.append(row)
    for artifact in artifacts:
        if artifact.get('format') in ('nsis', 'iso'):
            owned = {r['dest'].casefold() for r in artifact['members']}
            prefix = artifact['destination_prefix'].casefold()+'/'
            if any(d.startswith(prefix) and d not in owned for d in dests):
                raise InstallError('NSIS component folder overlaps another payload')
            for name, digest in NSIS_HELPER_HASHES.items():
                if not any(r['dest'] == NSIS_HELPER+'/'+name and r['sha256'] == digest for r in manifest['payload']['members']):
                    raise InstallError('NSIS requires the pinned bundled archive reader')
    for row in planned_receipts(manifest, chosen, expected_files):
        dests.add(row['dest'].casefold())
        expected_files.append(row)
    for dest in dests:
        if any(str(p) in dests for p in PurePosixPath(dest).parents):
            raise InstallError('Release defines a file as a parent directory')
    from installer_storage import requirement
    need = requirement(expected_files, artifacts)['required_bytes']
    return chosen, artifacts, expected_files, need



class InstallationProgress:
    """Actual selected download/write/readback bytes; final publication owns 100%."""
    def __init__(self, events, artifacts, files):
        self.events=events or (lambda **kw:None)
        self.total=sum(a['bytes'] for a in artifacts)+2*sum(r['bytes'] for r in files)
        self.completed=0;self.phase='preparing';self.label='Preparing installation'
        self.size=0;self.done=0;self.member=None;self.member_done=0

    def start(self,phase,label,size=0):
        self.phase=phase;self.label=label;self.size=size;self.done=0;self.member=None;self.member_done=0
        self.send()

    def advance(self,label,done,total):
        self.done=max(0,min(done,self.size));self.send()

    def file(self,row,done,total):
        name=row['dest']
        if self.member!=name:self.member=name;self.member_done=0
        self.done+=max(0,done-self.member_done);self.member_done=done;self.send()

    def finish(self):
        self.done=self.size;self.send();self.completed+=self.size;self.done=0

    def send(self):
        self.events(kind='progress',phase=self.phase,message=self.label,done=self.done,total=self.size,
                    overall_done=min(self.total,self.completed+self.done),overall_total=self.total)


def install(package, destination, selected, stop=None, progress=None, events=None):
    """Build a new directory beside the requested final path, then publish it."""
    stop = stop or threading.Event()
    progress = progress or (lambda *_: None)
    package = Path(package).absolute()
    checked_path(package.parent, package.name)
    manifest_path = package / 'release.json'
    manifest = read_manifest(package)
    chosen, artifacts, expected_files, need = plan(manifest, selected)
    meter=InstallationProgress(events,artifacts,expected_files)
    meter.start("preparing","Checking selected files and disk space")
    destination = Path(destination).absolute()
    if not destination.name or destination == destination.parent:
        raise InstallError('Choose a new installation folder, not a drive root')
    checked_path(destination.parent, destination.name)
    in_place = destination == package
    if destination.exists() and not in_place:
        raise InstallError('Choose a new folder. Existing folders are never overwritten.')
    publish_names = sorted({relative(row['dest']).parts[0] for row in expected_files} | {'INSTALL_RECEIPT.json'})
    if in_place:
        for name in publish_names:
            if checked_path(destination, name).exists():
                raise InstallError('An installation item already exists beside the installer: '+name+'. Move the installer package to an empty folder; existing files will not be overwritten.')
    work_parent = destination if in_place else destination.parent
    from installer_storage import check_space
    space = check_space(work_parent, expected_files, artifacts)
    progress(space['message'], 0, 0)
    payload = checked_path(package, manifest['payload']['file'])
    if payload.stat().st_size != manifest['payload']['bytes'] or sha256(payload) != manifest['payload']['sha256']:
        raise InstallError('Bundled public payload checksum failed')
    # Cache is bound to the release digest, not to machine/user-specific configuration.
    release_hash = sha256(manifest_path)
    cache = checked_path(work_parent, '.PortalAI-downloads-' + release_hash[:16])
    downloaded = []
    for artifact in artifacts:
        if stop.is_set():
            raise Cancelled('Paused before installation')
        meter.start('download',artifact['id'],artifact['bytes'])
        def download_progress(label,done,total):
            progress(label,done,total);meter.advance(label,done,total)
        downloaded.append((artifact, download_artifact(artifact, package, cache, stop, download_progress)))
        meter.finish()
    # Downloads are now on disk; recheck the remaining extraction requirement.
    check_space(work_parent, expected_files, [])
    stage = checked_path(work_parent, '.PortalAI-installing-' + uuid.uuid4().hex[:12])
    stage.mkdir()
    progress('Installing and verifying files in ' + str(stage), 0, len(expected_files))
    progress('Installing bundled application files', 0, 0)
    meter.start('install','Bundled application files',sum(r['bytes'] for r in manifest['payload']['members']))
    extract_allowlist(payload, manifest['payload']['members'], stage, stop, meter.file)
    meter.finish()
    for artifact, path in downloaded:
        progress('Installing ' + artifact['id'], 0, 0)
        meter.start('install',artifact['id'],sum(r['bytes'] for r in artifact['members']))
        if artifact.get('format') == 'file':
            if len(artifact['members']) != 1:
                raise InstallError('Direct files require one destination')
            row = artifact['members'][0]
            with path.open('rb') as source:
                write_verified(source, checked_path(stage, row['dest']), row, stop, meter.file)
        elif artifact.get('format') == 'zip':
            extract_allowlist(path, artifact['members'], stage, stop, meter.file)
        elif artifact.get('format') == 'tar':
            extract_tar_allowlist(path, artifact['members'], stage, stop, meter.file)
        elif artifact.get('format') in ('nsis', 'iso'):
            extract_nsis_allowlist(path, artifact, stage, stop, meter.file)
        else:
            raise InstallError('Unsupported pinned artifact format')
        meter.finish()
    if stop.is_set():
        raise Cancelled('Installation paused before publication')
    meter.start('verify','Verifying installed files',sum(r['bytes'] for r in expected_files if 'receipt_utf8' not in r))
    for row in expected_files:
        if 'receipt_utf8' in row:
            continue
        target = checked_path(stage, row['dest'])
        if target.stat().st_size != row['bytes'] or sha256(target,lambda done,total:meter.file(row,done,total)) != row['sha256']:
            raise InstallError('Final readback failed: ' + row['dest'])
    meter.finish()
    # Receipts are created only after every selected public payload passes full
    # readback, and before publication. A failed/cancelled install cannot mark an
    # absent optional model as verified.
    for row in expected_files:
        if 'receipt_utf8' not in row:
            continue
        target = checked_path(stage, row['dest'])
        meter.start('install','Writing installation receipts',row['bytes'])
        with io.BytesIO(row['receipt_utf8'].encode('utf-8')) as stream:
            write_verified(stream, target, row, stop, meter.file)
        meter.finish()
        meter.start('verify','Verifying installation receipts',row['bytes'])
        if target.stat().st_size != row['bytes'] or sha256(target) != row['sha256']:
            raise InstallError('Generated receipt readback failed: '+row['dest'])
        meter.finish()
    # Snapshot only fingerprint-verified public runtime files. The storage plan
    # reserves these backups before any dependency downloads begin.
    meter.start('recovery','Creating verified executable recovery backups')
    progress('Creating verified executable recovery backups', 0, 0)
    import importlib.util
    app_root = checked_path(stage, 'PortalAI Windows')
    spec = importlib.util.spec_from_file_location('installed_executable_recovery', app_root / 'Agent/executable_recovery.py')
    repair = importlib.util.module_from_spec(spec); spec.loader.exec_module(repair)
    recovery_files = [dict(path=row['dest'][len('PortalAI Windows/'):], bytes=row['bytes'], sha256=row['sha256'])
                      for row in expected_files if row['dest'].startswith('PortalAI Windows/')]
    def recovery_cancel():
        if stop.is_set(): raise Cancelled('Paused during executable backup creation')
    repair.register(app_root, recovery_files, manifest['release'], recovery_cancel)
    report = {'release': manifest['release'], 'release_sha256': release_hash,
              'components': [c['id'] for c in chosen], 'verified_files': len(expected_files),
              'accounts_created': False, 'projection_connections_created': False}
    (stage / 'INSTALL_RECEIPT.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    # On Windows rename fails when a concurrent process creates the target.
    meter.start('publish','Publishing the verified installation')
    if in_place:
        # Publish only this release's verified top-level entries. Never merge
        # into or replace unrelated folders already beside the installer.
        for name in publish_names:
            if checked_path(destination, name).exists():
                raise InstallError('Destination appeared during installation; verified staging was retained: '+str(stage))
        journal = stage / 'PUBLISH_JOURNAL.json'
        published = []
        try:
            for name in publish_names:
                journal.write_text(json.dumps({'destination': str(destination), 'published': published, 'next': name}), encoding='utf-8')
                checked_path(stage, name).rename(checked_path(destination, name))
                published.append(name)
        except Exception as exc:
            raise InstallError('Publication interrupted; do not retry blindly. Review '+str(journal)+'. '+str(exc)) from exc
        journal.unlink()
        stage.rmdir()
        return report
    if destination.exists():
        raise InstallError('Destination appeared during installation; completed staging was retained')
    stage.rename(destination)
    return report
