"""Mac entry to the current platform-independent HA installer and deployment ZIP."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

HERE=Path(__file__).resolve().parent
PACKAGE=HERE/'HomeAssistant'

def prepare(output):
    spec=importlib.util.spec_from_file_location('ha_install',PACKAGE/'install.py')
    installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
    manifest=installer.verify_package(PACKAGE)
    names=sorted([*manifest,'SHA256SUMS.json'])
    output=Path(output).resolve()
    if output.is_relative_to(PACKAGE.resolve()):raise ValueError('Choose output outside the HA payload')
    if output.exists() or output.is_symlink():raise ValueError('Output already exists; choose a new filename')
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'x',zipfile.ZIP_DEFLATED) as archive:
        for name in names:
            data=installer.within(PACKAGE,name).read_bytes()
            if name in manifest and hashlib.sha256(data).hexdigest()!=manifest[name]:raise ValueError('Payload changed during preparation')
            archive.writestr('HomeAssistant/'+name,data)
    with zipfile.ZipFile(output) as archive:
        assert archive.testzip() is None
        for name,digest in manifest.items():
            if hashlib.sha256(archive.read('HomeAssistant/'+name)).hexdigest()!=digest:raise ValueError('Prepared ZIP verification failed')
    digest=hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name+'.sha256').write_text(digest+'  '+output.name+'\n',encoding='utf-8')
    print('Verified deployment ZIP: '+str(output))
    print('On the trusted HA terminal, extract outside www and run: sh HomeAssistant/install.sh wizard')
    print('Use the existing PUBLIC device ID. Existing pairings are preserved; recovery needs separate approval.')
    return output

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('install','prepare','verify','plan'))
    parser.add_argument('--config');parser.add_argument('--device-id');parser.add_argument('--output',type=Path)
    parser.add_argument('--files-only',action='store_true')
    args=parser.parse_args(argv)
    subprocess.run([sys.executable,'-B','-I',str(PACKAGE/'install.py'),'verify'],check=True)
    mode=args.mode
    if mode is None:
        print('1. Install/configure an existing writable HA config folder/share\n2. Prepare a ZIP for a trusted HA terminal')
        choice=input('Choose 1 or 2 (Enter for Install): ').strip()
        if choice not in ('','1','2'):raise ValueError('Invalid choice; no changes made')
        mode='prepare' if choice=='2' else 'install'
    if args.device_id and not re.fullmatch('[0-9a-f]{32}',args.device_id):raise ValueError('Device ID must be 32 lowercase hex characters')
    if mode=='verify':return
    if mode=='prepare':return prepare(args.output or HERE/'Deployments'/('PortalAI-HA-'+time.strftime('%Y%m%d-%H%M%S')+'.zip'))
    command=[sys.executable,'-B','-I',str(PACKAGE/'install.py'), 'plan' if mode=='plan' else 'install' if args.config and args.device_id else 'wizard']
    if args.config:command+=['--config',args.config]
    if args.device_id:command+=['--device-id',args.device_id]
    if args.files_only:command+=['--files-only']
    subprocess.run(command,check=True)

if __name__=='__main__':
    try:main()
    except (OSError,ValueError,subprocess.CalledProcessError) as error:
        print('Setup stopped: '+str(error),file=sys.stderr);sys.exit(1)
