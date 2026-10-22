"""Activate only the verified, tested Windows 9.0.2 portable extraction."""
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Tools'),str(ROOT/'Agent')]
from fetch_windows_kicad import SHA256, SIZE, URL


def digest(path):
    with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


def main():
    archive=ROOT/'Runtime/Downloads/KiCad-9.0.2.exe'
    if archive.stat().st_size!=SIZE or digest(archive)!=SHA256:raise ValueError('Installer size/hash mismatch')
    for name,expected in [('7z.exe','95fff19b73eff77c87c0d7bd32822e43fb90dd2932459f962eb532d8dfb6ba53'),
                          ('7z.dll','899cd73d7fc60e1c1c35c7de0f5bed3dc69bfe2cecbd48014d868a347970a0b1')]:
        if digest(ROOT/'Tools/7zip'/name)!=expected:raise ValueError('Extractor hash mismatch: '+name)
    stage=ROOT/'Tools/KiCad.staging-9.0.2';target=ROOT/'Tools/KiCad'
    for path in (stage,target):
        if path.resolve().parent!=ROOT/'Tools' or path.is_symlink():raise ValueError('Invalid activation scope')
        if path.exists() and getattr(path.lstat(),'st_file_attributes',0)&0x400:raise ValueError('Linked activation scope')
    report_path=ROOT/'Maintenance/Validation/GUIPolish20261011/kicad-staging/kicad-smoke.json'
    report=json.loads(report_path.read_text())
    if not (report['passed'] and Path(report['payload'])==stage and report['version']=='9.0.2'):
        raise ValueError('Staging exports were not verified')
    if target.exists():raise FileExistsError('Existing KiCad is never overwritten')
    # The NSIS uninstall stub is not useful in an extracted portable distribution.
    (stage/'uninstall.exe.nsis').unlink(missing_ok=True)
    rows=[]
    for file in sorted(stage.rglob('*')):
        if file.is_symlink() or getattr(file.lstat(),'st_file_attributes',0)&0x400:raise ValueError('Linked payload')
        if file.is_file():rows.append({'path':file.relative_to(stage).as_posix(),'bytes':file.stat().st_size,'sha256':digest(file)})
    receipt={'verified':True,'version':'9.0.2','source':URL,'archive_bytes':SIZE,'archive_sha256':SHA256,
        'checksum_source':'https://raw.githubusercontent.com/microsoft/winget-pkgs/master/manifests/k/KiCad/KiCad/9.0.2/KiCad.KiCad.installer.yaml',
        'payload_bytes':sum(row['bytes'] for row in rows),'files':rows,
        'validation':str(report_path.relative_to(ROOT)),'portable_extraction':True,'installer_executed':False}
    pending=ROOT/'Maintenance/Imports/windows-kicad.pending.json'
    with pending.open('x',encoding='utf-8') as output:
        json.dump(receipt,output,indent=2);output.flush();os.fsync(output.fileno())
    stage.rename(target)
    final=ROOT/'Maintenance/Imports/windows-kicad.json'
    if final.exists():raise FileExistsError('KiCad receipt already exists; pending receipt retained')
    pending.rename(final)
    print(json.dumps({'activated':str(target),'files':len(rows),'payload_bytes':receipt['payload_bytes'],'receipt':str(final)}))


if __name__=='__main__':main()
