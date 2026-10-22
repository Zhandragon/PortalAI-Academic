"""Tiny real Comfy CPU dtype check, before the separately bounded model load."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
from validation_artifacts import ValidationArtifacts
from runtime_policy import atomic_json


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir',required=True)
    parser.add_argument('--case',required=True)
    args=parser.parse_args()
    artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    folder=artifacts.path(args.case)
    if folder.parent!=artifacts.path() or not folder.is_dir() or not folder.name.startswith('vace-reference-'):
        raise ValueError('CPU primitive requires the existing synthetic VACE case directory')
    report={'passed':False,'backend':'cpu','full_model_loaded':False,'physical_radeon_validated':False}
    try:
        sys.path.insert(0,str(ROOT/'Generative/ComfyUI_windows_portable/ComfyUI'))
        sys.argv=['vace_cpu_primitive','--cpu','--fp16-unet']
        import comfy.options
        comfy.options.enable_args_parsing()
        import torch
        torch.set_num_threads(2);torch.set_num_interop_threads(1)
        import comfy.model_management as management
        import comfy.ops as ops
        from comfy.quant_ops import QuantizedTensor
        if management.get_torch_device().type!='cpu':raise RuntimeError('Primitive selected a non-CPU device')
        stored=management.unet_dtype(device=torch.device('cpu'),weight_dtype=torch.float16)
        compute=management.unet_manual_cast(stored,torch.device('cpu'))
        if stored!=torch.float16 or compute!=torch.float32:
            raise RuntimeError('Comfy CPU dtype policy differs from the inspected FP16-storage/FP32-compute contract')
        with torch.inference_mode():
            linear=ops.manual_cast.Linear(16,16,bias=False,device='cpu',dtype=stored)
            linear.weight.fill_(1)
            value=linear(torch.ones((2,16),dtype=compute))
            if linear.weight.dtype!=stored or value.dtype!=compute or not torch.all(value==16).item():
                raise RuntimeError('FP16 storage/manual FP32 CPU operation failed')
            mixed=ops.mixed_precision_ops({},torch.float16,full_precision_mm=True)
            quantized=mixed.Linear(16,16,bias=False,device='cpu',dtype=torch.float16)
            marker=torch.tensor(list(json.dumps({'format':'float8_e4m3fn'}).encode()),dtype=torch.uint8)
            quantized.load_state_dict({'weight':torch.ones((16,16),dtype=torch.float32).to(torch.float8_e4m3fn),
                                       'weight_scale':torch.tensor(1.),'comfy_quant':marker})
            result=quantized(torch.ones((2,16),dtype=torch.float32))
            if (not isinstance(quantized.weight,QuantizedTensor) or quantized.weight._qdata.dtype!=torch.float8_e4m3fn
                    or result.dtype!=torch.float32 or not torch.all(result==16).item()):
                raise RuntimeError('FP8-storage/full-precision CPU operation failed')
        report.update(passed=True,unet_storage=str(stored),unet_compute=str(compute),
                      text_linear_storage='torch.float8_e4m3fn',text_linear_compute='torch.float32')
    except Exception as exc:report['error']=str(exc)
    atomic_json(folder/'primitive.json',report)
    print(json.dumps(report,ensure_ascii=True))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
