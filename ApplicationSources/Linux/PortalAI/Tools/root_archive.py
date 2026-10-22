"""Reversible root declutter, using a verified source snapshot and move journal."""
import fnmatch
import hashlib
import json
from pathlib import Path
import time

PATTERNS = ('Install_PortableAI_v*.cmd','Install_PortalAI_v*.cmd','README_v*',
            'Run_*_v*.cmd','Stop_All_PortableAI_v*.cmd','Test_Qwen_Startup_v*.cmd',
            'Verify_Startup_Wiring_v*.cmd','Apply_Portability_Fixes_v*.cmd')
EXACT = {'PortableAI.lnk','PortalAI.lnk','PortableAI Launcher.vbs',
         'Bootstrap_PortableAI.cmd','bootstrap_portable_python.ps1','inspect_portableai.py',
         'PortableAI.ico','ai_tools.log','ai_tools.erc',
         'PortableAI_Master_Instructions_v43.txt','PortableAI_Master_Instructions_v44.txt',
         'README.txt','MANIFEST.json','MANIFEST_SHA256.json','MANIFEST_SHA256.txt',
         'RECOVERY_FROM_v15_129_FAILED_INSTALL.txt','Scientific_Instructions_Addendum_v15_129.txt'}


def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def plan(root):
    root=Path(root).resolve()
    return [p for p in root.iterdir() if p.is_file() and not p.is_symlink()
            and (p.name in EXACT or any(fnmatch.fnmatchcase(p.name,pat) for pat in PATTERNS))]


def archive(root, apply=False):
    root=Path(root).resolve();paths=plan(root)
    result={'policy':'Archive only; no deletion. Old installers are historical and must not be run from the archive.',
            'candidates':[p.name for p in paths],'moved':[]}
    if not apply or not paths:return result
    baseline=root/'Backups/PortalGUI_before_20261009/manifest.json'
    record=json.loads(baseline.read_text());known={x['path']:x['sha256'] for x in record['files']}
    source=baseline.with_name('source.zip')
    if digest(source)!=record['archive_sha256']:raise RuntimeError('Recovery archive checksum mismatch')
    for p in paths:
        if known.get(p.name)!=digest(p):raise RuntimeError(f'Changed/unbacked root file; review first: {p.name}')
    destination=root/'Maintenance/Archive'/time.strftime('Root-%Y%m%d-%H%M%S')
    destination.mkdir(parents=True,exist_ok=False)
    journal=destination/'_archive-journal.json'
    for p in paths:
        target=destination/p.name
        if p.parent.resolve()!=root or not target.resolve().is_relative_to(root):raise RuntimeError('Archive path escaped root')
        row={'from':p.name,'to':target.relative_to(root).as_posix(),'sha256':digest(p),'moved':False}
        result['moved'].append(row);journal.write_text(json.dumps(result,indent=2),encoding='utf-8')
        p.rename(target)
        if digest(target)!=row['sha256']:raise RuntimeError('Archive verification failed')
        row['moved']=True;journal.write_text(json.dumps(result,indent=2),encoding='utf-8')
    (destination/'READ_ME.txt').write_text('Historical files, preserved for recovery. Do not run old installers here.\nRestore to original root locations only after reviewing the current version and manifest.\n',encoding='utf-8')
    return result
