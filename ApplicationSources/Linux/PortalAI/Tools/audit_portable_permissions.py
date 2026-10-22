"""Read-only Windows access audit using only the cross-machine Authenticated Users SID."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]


from windows_portable_access import PortableAccess


PUBLIC_ROOTS=('Agent','ControlCenter','Launchers','Runtime','LLM/models','LLM/backends','Tools',
              'Voice','Scientific','SpeechToText','Music','MusicUnderstanding','Video','Generative',
              'Runtimes','Models','Services/MMAudio')
EXCLUDED={'__pycache__','.git','outputs','output','inputs','input','userdata','user','temp','tmp','logs','cache','.cache',
          '.runtime','uv-cache','gradio_outputs'}


def audit(root=ROOT, progress=None, trees=PUBLIC_ROOTS):
    from portable_fs import walk, Path as LongPath
    from profile_paths import PRIVATE_PREFIXES
    root=LongPath(root).resolve();probe=PortableAccess();errors=[];counts={};links=[]
    def private(path):
        relative=LongPath(path).relative_to(root).as_posix().lower()
        return any(relative==prefix.lower() or relative.startswith(prefix.lower()+'/') for prefix in PRIVATE_PREFIXES)
    def error(path,reason):errors.append({'path':str(LongPath(path).relative_to(root)),'error':reason})
    def inspect(path):
        try:
            if not probe.allows(path):error(path,'Authenticated Users lacks read/execute')
        except OSError as exc:error(path,type(exc).__name__)
    try:
        inspect(root)
        for name in ('PortalAI.exe','PortalAI.sh'):
            if (root/name).is_file():inspect(root/name)
        if not set(trees) <= set(PUBLIC_ROOTS):raise ValueError('Only named public runtime trees may be audited')
        for relative in trees:
            count=0;base=root/relative
            if not base.exists():continue
            for folder,dirs,files in walk(base,followlinks=False,onerror=lambda e:error(e.filename,type(e).__name__)):
                inspect(LongPath(folder));count+=1
                dirs[:]=[d for d in dirs if d.lower() not in EXCLUDED and not private(LongPath(folder)/d) and not any(t in d for t in ('-preserved','-inaccessible','-stage','-permissions-recovery'))]
                for name in list(dirs)+files:
                    path=LongPath(folder)/name
                    if private(path) or name.lower() in ('.env','token','stored_tokens'):continue
                    try:
                        if path.is_symlink() or getattr(path.lstat(),'st_file_attributes',0)&0x400:
                            links.append(str(path.relative_to(root)))
                            if name in dirs:dirs.remove(name)
                            continue
                    except OSError as exc:error(path,type(exc).__name__);continue
                    if name in files:inspect(path);count+=1
            counts[relative]=count
            if progress:progress({'tree':relative,'objects':count,'errors_so_far':len(errors)})
        return {'passed':not errors and not links,'counts':counts,'errors':errors,'unfollowed_links':links,
                'acl_descriptors':len(probe.cache),'scope':'Named public runtime/source/model trees, excluding retained originals and vendor user/cache/output state; NTFS read/execute only, not application/GPU or mount-policy validation'}
    finally:probe.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir')
    parser.add_argument('--tree',action='append',choices=PUBLIC_ROOTS)
    args=parser.parse_args()
    result=audit(progress=lambda row:print(json.dumps(row),flush=True),trees=args.tree or PUBLIC_ROOTS)
    if args.artifacts_dir:
        from validation_artifacts import ValidationArtifacts
        artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
        artifacts.path('portable-access.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('errors','unfollowed_links')},indent=2))
    raise SystemExit(not result['passed'])
