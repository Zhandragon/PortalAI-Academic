"""Bounded public-file checks for current features; never imports model runtimes."""
import os
import json
import re
from pathlib import Path

# Required first-party source versus optional installed runtime/model assets.
FEATURES = {
    'home_assistant': ('Home Assistant / Projection',
        ('ControlCenter/native_workflow.py','ControlCenter/native_chat_command.py','ControlCenter/native_thumbnail.py'),
        ('@Utilities/PortalAI-Projection/app/projection_worker.py','@Utilities/PortalAI-Projection/app/native_transport.py',
         '@Utilities/PortalAI HA Setup/Install PortalAI HA.cmd')),
    'recovery': ('Portable Recovery', ('Launchers/Recover_PortalAI_Login.cmd','Tools/recover_profile_login.py'),
        ('@Utilities/PortalAI-Projection/app/recovery_runtime.py','@Utilities/PortalAI-Projection/app/recovery_transport.py',
         '@Utilities/PortalAI-Projection/Start HA Recovery.cmd')),
    'runtime_repair': ('Runtime Repair', ('Tools/Repair_Account_Runtime.py','Tools/portable_pip_runner.py','Tools/portable_pip_paths.py'),
        ('Runtime/AccountPython/packages/cryptography/__init__.py','Maintenance/Imports/account-runtime-lock.json')),
    'musicgen': ('MusicGen CPU', ('Agent/music_cpu.py','Agent/music_cpu_entry.py'),
        tuple('Music/MusicGen-small/'+name for name in ('config.json','generation_config.json','model.safetensors',
              'preprocessor_config.json','special_tokens_map.json','spiece.model','tokenizer.json','tokenizer_config.json'))),
    'demucs': ('Offline Demucs', ('Agent/windows_demucs.py','MusicUnderstanding/runtime_driver.py'),
        ('MusicUnderstanding/runtime/python.exe','MusicUnderstanding/runtime/Lib/site-packages/demucs/__init__.py',
         'MusicUnderstanding/models/HTDemucs/955717e8.safetensors')),
    'ffmpeg': ('FFmpeg / Media Tools', ('Agent/media_edit_bridge.py','Agent/platform_runtime.py'),
        ('Tools/ffmpeg/bin/ffmpeg.exe','Tools/ffmpeg/bin/ffprobe.exe')),
    'vm': ('Offline VM', ('Agent/vm_runner.py','Tools/check_execution_modes.py'),
        ('Runtime/QEMU/windows-x64/qemu-system-x86_64.exe','Runtime/VM/alpine-3.24.2/boot/vmlinuz-virt',
         'Runtime/VM/alpine-3.24.2/boot/initramfs-virt')),
    'native_flux': ('Native FLUX', ('Agent/native_flux.py','Agent/sdcpp_bridge.py'),
        ('Maintenance/Imports/native-flux-klein4.json','Maintenance/Imports/native-flux-klein4-alternate-encoder.json',
         'Generative/ComfyUI_windows_portable/ComfyUI/models/diffusion_models/flux-2-klein-4b-Q4_0.gguf',
         'LLM/models/Qwen3-4B-Q4_K_M.gguf',
         'Generative/ComfyUI_windows_portable/ComfyUI/models/text_encoders/flux2-klein-4b-uncensored-q4_k_m.gguf',
         'Generative/ComfyUI_windows_portable/ComfyUI/models/vae/flux2-vae.safetensors')),
}
MEDIA_FEATURES = ('musicgen','demucs','ffmpeg','native_flux')
PINNED_SIZES = {'MusicUnderstanding/models/HTDemucs/955717e8.safetensors':84025440,
                'Music/MusicGen-small/model.safetensors':2364427288}

def _path(root, relative):
    return root.parent/relative[1:] if relative.startswith('@Utilities/') else root/relative

def account_repair_wheels(root):
    """Inspect the current or retained legacy public receipt without hashing wheels."""
    label='Runtime Repair pinned wheel inventory'
    try:
        receipt=root/'Maintenance/Imports/account-runtime-lock.json'
        if receipt.stat().st_size>128*1024:raise ValueError('Account runtime receipt is oversized')
        assets=json.loads(receipt.read_text(encoding='utf-8'))['assets']
        if not isinstance(assets,list) or not 1<=len(assets)<=100:raise ValueError('Invalid asset list')
        missing=[];names=set();seen=set()
        for row in assets:
            rel=Path(row['wheel'])
            if (rel.parent.as_posix() not in ('Runtime/AccountPython/wheelhouse','Cache/account-runtime-wheelhouse') or
                rel.suffix!='.whl' or rel.name.casefold() in seen or type(row['bytes']) is not int or
                not 0<row['bytes']<=128*1024**2 or not re.fullmatch('[a-f0-9]{64}',row['sha256'])):
                raise ValueError('Unreviewed wheel path or pin')
            seen.add(rel.name.casefold());names.add(row['name'].replace('_','-'))
            p=root/rel
            if not p.is_file() or p.stat().st_size!=row['bytes']:missing.append(rel.name)
        if not {'cryptography','eth-account'}<=names:raise ValueError('Incomplete package receipt')
        return {'status':'WARN' if missing else 'PASS','label':label,
            'detail':('Missing/size mismatch: '+', '.join(missing) if missing else str(len(assets))+' pinned wheel names and sizes present')+
                     '; full SHA-256 and wheel RECORD verification remain mandatory before repair.'}
    except FileNotFoundError:
        return {'status':'WARN','label':label,'detail':'Pinned account runtime repair receipt is not installed.'}
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
        return {'status':'FAIL','label':label,'detail':'Cannot validate public repair inventory: '+str(exc)}

def rows(root, component='all'):
    root=Path(root).resolve()
    keys=tuple(FEATURES) if component=='all' else (component,)
    result=[]
    for key in keys:
        title,sources,assets=FEATURES[key]
        if key=='vm' and os.name!='nt':
            assets=('Runtime/QEMU/linux-x64/qemu-system-x86_64',*assets[1:])
        for label,paths,required in [('source',sources,True),('installed assets',assets,False)]:
            if os.name!='nt' and key in ('demucs','runtime_repair','ffmpeg') and not required:
                result.append({'status':'WARN','label':title+' Windows assets','detail':'Windows layout not checked on this OS; use its platform-specific diagnostic.'})
                continue
            try:
                missing=[]
                for rel in paths:
                    p=_path(root,rel)
                    if not p.exists() or (p.is_file() and p.stat().st_size==0):missing.append(rel)
                    elif rel in PINNED_SIZES and p.stat().st_size!=PINNED_SIZES[rel]:missing.append(rel+' (pinned size mismatch)')
                    elif p.is_dir() and next(p.iterdir(),None) is None:missing.append(rel+' (empty)')
                status=('FAIL' if required else 'WARN') if missing else 'PASS'
                detail='Missing/incomplete: '+', '.join(missing) if missing else 'Public file presence only: '+', '.join(paths)
                if not required:detail+='; listed model sizes are checked where pinned. No hash/import/inference, connection or pairing validation.'
                result.append({'status':status,'label':title+' '+label,'detail':detail})
            except OSError as exc:
                result.append({'status':'FAIL','label':title+' '+label,'detail':'Storage read failed: '+str(exc)})
        if key=='runtime_repair' and os.name=='nt':result.append(account_repair_wheels(root))
    return result
