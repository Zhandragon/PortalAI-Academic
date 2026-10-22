"""ROCm-package CPU operations and ACE-Step API contract, without loading weights."""
import json
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from acestep_amd_entry import activate, import_api, request_params


def main():
    activate()
    import torch
    import soundfile
    from runtime_policy import atomic_json
    from vector_quantize_pytorch import ResidualFSQ
    Handler,Params,Config,generate=import_api()
    torch.set_num_threads(2)
    quantizer=ResidualFSQ(dim=8,levels=[3,3],num_quantizers=2)
    with torch.inference_mode():
        encoded=quantizer(torch.randn(1,4,8))[0]
        attention=torch.nn.functional.scaled_dot_product_attention(
            torch.ones(1,2,4,8),torch.ones(1,2,4,8),torch.ones(1,2,4,8))
    assert torch.isfinite(encoded).all() and torch.isfinite(attention).all()
    handler=Handler();seen={}
    def fake_diffusion(**kwargs):
        seen.update(kwargs)
        return {'success':True,'audios':[{'tensor':torch.zeros(2,48000),'sample_rate':48000}]}
    handler.generate_music=fake_diffusion
    params=request_params(Params,'A short tune','unused lyrics',True,10,42)
    result=generate(handler,None,params,Config(batch_size=1,allow_lm_batch=False,
        use_random_seed=False,seeds=[42],audio_format='flac'),save_dir=None)
    assert result.success and len(result.audios)==1, result.error
    assert seen['lyrics']=='[Instrumental]' and seen['batch_size']==1 and seen['inference_steps']==8
    assert result.audios[0]['params']['seed']==42
    with tempfile.TemporaryDirectory(dir=ROOT/'Cache/tmp') as temp:
        path=Path(temp)/'codec-test.flac'
        soundfile.write(path,result.audios[0]['tensor'].numpy().T,48000,format='FLAC')
        audio,rate=soundfile.read(path)
        assert rate==48000 and audio.shape==(48000,2)
    report={'passed':True,'torch':torch.__version__,'device':'cpu','weights_loaded':False,
        'physical_radeon_test':False,'music_quality_test':False,
        'checks':['ROCm-package CPU quantizer and attention','ACE-Step request/result contract with a fake diffusion handler',
                  'instrumental flag and deterministic seed','FLAC write/read'],
        'scope':'Dependency/API compatibility only; real AMD music inference still pending'}
    atomic_json(ROOT/'Maintenance/Reports/amd-music-smoke.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
