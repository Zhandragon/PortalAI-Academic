"""Read-only virtual test disk; never exposes a host directory to the guest."""
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Runtime/LinuxPackages/extras'),str(ROOT/'Agent')]
import pycdlib
from runtime_policy import require_space
sys.path.insert(0,str(Path(__file__).resolve().parent))
from validation_artifacts import ValidationArtifacts,add_artifact_arguments,require_output_space

SOURCE_EXCLUDED={'input','output','outputs','temp','tmp','user','cache','.cache','logs','jobs','checkpoints','.git','__pycache__'}
# These exact upstream Python packages are code, despite their directory names.
SOURCE_PACKAGES={('comfy_api','input'),('api','jobs')}


def project_source_files(base):
    """Include distributed source/config only; never follow vendor user/cache links."""
    base=Path(base)
    def linked(path):
        return path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction())
    if any(linked(path) for path in (base,*base.parents)):
        raise ValueError('Linked project source root cannot enter synthetic media ISO')
    for folder,dirs,names in os.walk(base,followlinks=False):
        folder=Path(folder)
        dirs[:]=[name for name in dirs if (name.casefold() not in SOURCE_EXCLUDED or
                 (folder/name).relative_to(base).parts in SOURCE_PACKAGES) and not linked(folder/name)]
        for name in names:
            file=folder/name
            if not linked(file) and file.is_file() and file.suffix in ('.py','.json','.yaml','.txt','.html','.js','.css'):
                yield file


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kicad-resources',action='store_true',help='Build only the verified KiCad resource ISO alongside the existing media ISO')
    add_artifact_arguments(parser)
    options=parser.parse_args()
    artifacts=ValidationArtifacts(ROOT,options.artifacts_dir)
    files={}
    if options.kicad_resources:
        import hashlib
        receipt=json.loads((ROOT/'Maintenance/Imports/linux-system-kicad-resources.json').read_text())
        for row in receipt['files']:
            file=ROOT/receipt['destination']/row['path']
            with file.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
            if digest!=row['sha256']:raise RuntimeError('KiCad resource checksum differs: '+row['path'])
            files[file.relative_to(ROOT).as_posix()]=file
        write_disk(files,artifacts,'kicad-resources.iso')
        return
    for rel in ('Runtime/LinuxPackages/media','Runtime/LinuxPackages/science','Runtime/LinuxPackages/extras',
                'Runtime/LinuxPackages/accounts','Runtime/LinuxPackages/musicunderstanding','Runtime/LinuxTorch/cpu','Runtime/StableDiffusion/linux-cpu',
                'Runtime/StableDiffusion/linux-vulkan','Scientific','LLM/backends/linux-cpu'):
        for file in (ROOT/rel).rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts:files[file.relative_to(ROOT).as_posix()]=file
    import hashlib
    receipt=json.loads((ROOT/'Maintenance/Imports/linux-system-kicad.json').read_text())
    for row in receipt['files']:
        file=ROOT/receipt['destination']/row['path']
        with file.open('rb') as source:digest=hashlib.file_digest(source,'sha256').hexdigest()
        if digest!=row['sha256']:raise RuntimeError('KiCad payload checksum differs: '+row['path'])
        files[file.relative_to(ROOT).as_posix()]=file
    # Only source from model projects; their large GPU weights are not needed for import checks.
    for rel in ('Video/MuseTalk/musetalk','Services/MMAudio/mmaudio','Music/ACE-Step-1.5/acestep',
                'Generative/ComfyUI_windows_portable/ComfyUI'):
        for file in project_source_files(ROOT/rel):
            if rel!='Generative/ComfyUI_windows_portable/ComfyUI' or file.relative_to(ROOT/rel).parts[0]!='models':
                files[file.relative_to(ROOT).as_posix()]=file
    from media_policy import SD15
    for rel in (SD15,'Voice/Piper/models/en_US-ljspeech-medium.onnx','Voice/Piper/models/en_US-ljspeech-medium.onnx.json'):
        files[rel]=ROOT/rel
    for file in (ROOT/'Voice/Piper/models').glob('*'):
        if file.is_file():files[file.relative_to(ROOT).as_posix()]=file
    for file in (ROOT/'SpeechToText/models').glob('whisper-base/*'):
        if file.is_file():files[file.relative_to(ROOT).as_posix()]=file
    for rel in ('LLM/models/Qwen3-1.7B-Q8_0.gguf',):files[rel]=ROOT/rel
    for rel in ('MusicUnderstanding/MOSS-Music/src','MusicUnderstanding/models/CLAP-larger-music',
                'MusicUnderstanding/cache/huggingface/hub/models--adefossez--HTDemucs/snapshots/cbc8a9b1a87023b7fd74e7b3412e6321c0eab003',
                'MusicUnderstanding/cache/huggingface/hub/models--adefossez--HTDemucs/refs'):
        for file in (ROOT/rel).rglob('*'):
            if file.is_file() and '__pycache__' not in file.parts:files[file.relative_to(ROOT).as_posix()]=file
    for file in (ROOT/'MusicUnderstanding/models/MOSS-Music-8B-Instruct').rglob('*'):
        if file.is_file() and file.suffix in ('.py','.json','.jinja','.txt') and '__pycache__' not in file.parts:
            files[file.relative_to(ROOT).as_posix()]=file
    for rel in ('MusicUnderstanding/runtime_driver.py',):files[rel]=ROOT/rel
    for file in (ROOT/'Maintenance/Imports').glob('*.json'):files[file.relative_to(ROOT).as_posix()]=file
    write_disk(files,artifacts,'media-science.iso')


def write_disk(files,artifacts,output_name):
    out=artifacts.path(output_name)
    part_name=Path(output_name).with_suffix('.part').as_posix()
    part=artifacts.path(part_name)
    require_output_space(ROOT,artifacts,sum(p.stat().st_size for p in files.values())+1024**3)
    iso=pycdlib.PyCdlib();iso.new(interchange_level=3,rock_ridge='1.09',vol_ident='PORTALAI_TEST')
    dirs={p.as_posix() for name in files for p in Path(name).parents if str(p)!='.'}
    mapping={'.':''};count=0
    for name in sorted(dirs,key=lambda x:(x.count('/'),x)):
        count+=1;path=Path(name);alias=mapping[path.parent.as_posix()]+'/D'+str(count)
        iso.add_directory(iso_path=alias,rr_name=path.name,file_mode=0o40555);mapping[name]=alias
    for index,(name,file) in enumerate(sorted(files.items())):
        path=Path(name);iso.add_file(str(file),iso_path=mapping[path.parent.as_posix()]+'/F'+str(index)+';1',
                                   rr_name=path.name,file_mode=0o100555)
    try:iso.write(str(part))
    finally:iso.close()
    # A logout or newly linked destination must not commit the completed image.
    artifacts.path(part_name).replace(artifacts.path(output_name))
    print(json.dumps({'disk':str(out),'files':len(files),'bytes':out.stat().st_size,'guest':'offline, read-only virtual optical disk'}))
if __name__=='__main__':main()
