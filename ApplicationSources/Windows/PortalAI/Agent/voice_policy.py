"""Installed voice capacity, effort linking and explicit independent TTS choices.

Capacity uses total hardware, never permission to allocate currently free memory.
Workers recheck RAM/VRAM and storage after the owned-model handoff.
"""
from pathlib import Path

GIB=1024**3
MODELS=('auto','qwen','piper')
LABELS={'auto':'Automatic','qwen':'Qwen TTS — expressive','piper':'Piper — lightweight'}


def preferences(settings):
    model=settings.get('tts_model','auto')
    if model not in MODELS:raise ValueError('Unknown TTS model selection')
    linked=settings.get('tts_link_effort',True)
    if type(linked) is not bool:raise ValueError('Voice effort link must be on or off')
    return {'tts_model':model,'tts_link_effort':linked}


def capabilities(root, hardware=None, *, probe=False):
    from runtime_policy import detect_hardware
    root=Path(root);hw=hardware if hardware is not None else detect_hardware()
    ram=int(hw.get('ram_total_bytes',hw.get('ram_available_bytes',0)))
    cuda=next((g for g in hw.get('gpus',[]) if g.get('index',0)==0 and g.get('backend','cuda')=='cuda'),{})
    amd=hw.get('amd_gpu',{})
    if probe and not cuda and hw.get('system')=='Windows':
        from tts_policy import with_amd_probe
        amd=with_amd_probe(hw,root).get('amd_gpu',{})
    gpu_ok=int(cuda.get('total_bytes',0))>=8*GIB or bool(amd.get('compute_ok') and int(amd.get('total_bytes',0))>=8*GIB)
    qram=12 if not cuda and amd.get('shared_memory',True) else 6
    qfiles=('Voice/Qwen3-TTS/qwen_tts_runner.py',
            'Voice/Qwen3-TTS/models/Qwen3-TTS-12Hz-1.7B-CustomVoice/config.json',
            'Voice/Qwen3-TTS/models/Qwen3-TTS-12Hz-1.7B-CustomVoice/model.safetensors',
            'Voice/Qwen3-TTS/.venv/Lib/site-packages/qwen_tts/__init__.py')
    pfiles=('Voice/Piper/models/en_US-joe-medium.onnx','Voice/Piper/models/en_US-joe-medium.onnx.json',
            'Voice/Piper/packages/piper/__init__.py','Voice/Piper/packages/onnxruntime/__init__.py')
    models={}
    for name,files,ram_gib,hardware_ok in [('qwen',qfiles,qram,gpu_ok),('piper',pfiles,3,True)]:
        missing=[p for p in files if not (root/p).is_file()]
        reason=('Local voice assets are incomplete' if missing else
                'Requires a supported CUDA/compute-probed ROCm GPU with 8 GiB VRAM' if not hardware_ok else
                f'Requires {ram_gib} GiB system RAM including reserve' if ram<ram_gib*GIB else '')
        models[name]={'id':name,'label':LABELS[name],'installed':not missing,'available':not reason,'reason':reason,
                      'ram_required_bytes':ram_gib*GIB,'vram_required_bytes':8*GIB if name=='qwen' else 0,
                      'missing_assets':missing,'requires_recheck':True,'preview_only':True}
    stt=root/'SpeechToText/models/whisper-base'
    return {'models':models,'automatic':('qwen' if models['qwen']['available'] else 'piper'),
            'effort':{'fast':'piper','balanced':'qwen' if models['qwen']['available'] else 'piper',
                      'deep':'qwen' if models['qwen']['available'] else 'piper'},
            'stt':{'model':'Whisper Base','device':'cpu','installed':all((stt/p).is_file() for p in ('model.bin','config.json','tokenizer.json','vocabulary.txt')),
                   'ram_required_bytes':3*GIB,'requires_recheck':True},
            'preview_only':True,'requires_recheck':True,'joint_loading':'Sequential owned chat/voice handoff; capacities are not added together.'}


def resolve(settings, level, capacity):
    pref=preferences(settings);requested=pref['tts_model'];linked=pref['tts_link_effort']
    if level not in ('fast','balanced','deep'):raise ValueError('Unknown effort level')
    chosen=(capacity['effort'][level] if linked else capacity['automatic']) if requested=='auto' else requested
    row=capacity['models'][chosen]
    if not row['available']:raise RuntimeError(row['label']+': '+row['reason'])
    return {**row,'requested':requested,'linked':linked,'effort':level,
            'selection_reason':('Automatic voice follows '+level+' effort' if linked else 'Automatic voice uses available hardware')
                if requested=='auto' else 'Explicit voice model selection'}


def effort_for_voice(model, current):
    if model=='piper':return 'fast'
    if model=='qwen':return 'deep' if current=='deep' else 'balanced'
    return current


def after_effort_change(settings, level):
    pref=preferences(settings)
    if pref['tts_link_effort'] and pref['tts_model']!='auto':
        pref['tts_model']='piper' if level=='fast' else 'qwen'
    return pref
