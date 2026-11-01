"""Incremental audio decoding for the installed Qwen3 12 Hz custom voice.

Capture complete codec frames from the existing talker; retain its text,
sampling and voice direction. Decode causal windows with 25 frames of left
context, as in Qwen's own tokenizer chunked_decode. No package files are edited.
"""
import json
import os
from pathlib import Path
import runpy
import time
import wave


def generate(root,data,instruction):
    started=time.monotonic();timing={}
    runner=runpy.run_path(str(Path(root)/'Voice/Qwen3-TTS/qwen_tts_runner.py'))
    import torch
    timing['imports_seconds']=round(time.monotonic()-started,3)
    import qwen_tts
    timing['voice_package_seconds']=round(time.monotonic()-started,3)
    model=runner['_load']('custom');tokenizer=model.model.speech_tokenizer
    timing['model_ready_seconds']=round(time.monotonic()-started,3)
    decoder=tokenizer.model.decoder;rate=int(tokenizer.get_output_sample_rate());upsample=int(decoder.total_upsample)
    folder=Path(data['stream_dir']);codes=[];pending=0;number=0;frames=0
    if rate!=24000 or upsample<=0:raise RuntimeError('Installed Qwen tokenizer is not compatible with incremental audio')
    original=tokenizer.decode
    with wave.open(data['output'],'wb') as complete:
        complete.setparams((1,2,rate,0,'NONE','not compressed'))
        def emit():
            nonlocal codes,pending,number,frames
            if not pending:return
            left=len(codes)-pending
            with torch.inference_mode():
                audio=decoder(torch.stack(codes,dim=-1))[:,:,left*upsample:]
                raw=(audio[0,0].float().clamp(-1,1)*32767).round().to(torch.int16).cpu().numpy().tobytes()
            frames+=len(raw)//2
            if frames*2>32*1024**2 or number>=256:raise RuntimeError('Incremental Qwen output exceeded its bound')
            # Backpressure bounds files and prevents synthesis outrunning playback.
            deadline=time.monotonic()+30
            while len(list(folder.glob('*.wav')))>=8:
                if time.monotonic()>deadline:raise TimeoutError('Speech playback stopped consuming audio')
                time.sleep(.05)
            target=folder/(str(number).zfill(4)+'.wav');temporary=target.with_suffix('.part')
            with wave.open(str(temporary),'wb') as chunk:chunk.setparams((1,2,rate,0,'NONE','not compressed'));chunk.writeframes(raw)
            with temporary.open('r+b') as stream:os.fsync(stream.fileno())
            os.replace(temporary,target);complete.writeframes(raw)
            if not number:timing['first_chunk_seconds']=round(time.monotonic()-started,3)
            number+=1;codes=codes[-25:];pending=0
        def observe(module,args,output):
            nonlocal pending
            value=output.hidden_states[-1]
            if value is None:return
            if value.ndim!=2 or value.shape[0]!=1:raise RuntimeError('Incremental voice supports one speaker at a time')
            if int(value[0,0])==model.model.config.talker_config.codec_eos_token_id:return
            codes.append(value.detach());pending+=1
            if pending>=12:emit()
        def finish(*args,**kwargs):
            emit()
            if not frames:raise RuntimeError('Qwen produced no incremental codec frames')
            return [],rate
        hook=model.model.talker.register_forward_hook(observe)
        try:
            tokenizer.decode=finish
            model.generate_custom_voice(text=data['text'],language='English',speaker='Ryan',instruct=instruction)
        finally:tokenizer.decode=original;hook.remove()
    timing['total_seconds']=round(time.monotonic()-started,3)
    print(json.dumps({'success':True,'file':data['output'],'sample_rate':rate,'mode':'custom','stream_chunks':number,'timing':timing}),flush=True)
