"""Invoked only behind the existing worker job/start gate. No network or GPU use."""
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'Agent')]


def main():
    from runtime_policy import memory_info
    if memory_info()[1]<2*1024**3:raise RuntimeError('Not enough free RAM for protein worker')
    from Scientific.protein_design import verify_assets
    verify_assets(ROOT,windows=os.name=='nt')
    if os.name=='nt':
        layer=ROOT/'Runtime/ProteinDesign/windows-cpu'
        sys.path[:0]=[str(layer),str(ROOT/'Runtime/ScientificPython/packages')]
    else:
        from linux_ml import activate
        layer=activate(ROOT,'cpu')
    import numpy as np
    import torch
    if not Path(torch.__file__).resolve().is_relative_to(layer) or torch.version.cuda or torch.version.hip:
        raise RuntimeError('Protein worker requires the isolated CPU Torch layer')
    torch.set_num_threads(2)
    sys.path.insert(0,str(ROOT/'Runtime/ProteinDesign/vendor'))
    from protein_mpnn_utils import ProteinMPNN,tied_featurize,_S_to_seq,_scores
    request=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    import random
    random.seed(request['seed']);np.random.seed(request['seed']);torch.manual_seed(request['seed'])
    device=torch.device('cpu')
    checkpoint=torch.load(ROOT/'Runtime/ProteinDesign/vendor/vanilla_model_weights/v_48_020.pt',map_location=device,weights_only=True)
    model=ProteinMPNN(num_letters=21,node_features=128,edge_features=128,hidden_dim=128,num_encoder_layers=3,num_decoder_layers=3,augment_eps=0,k_neighbors=checkpoint['num_edges'])
    model.load_state_dict(checkpoint['model_state_dict']);model.eval()
    features=tied_featurize([request['protein']],device,{'design':(['A'],[])},{'design':{'A':request['fixed_positions']}})
    X,S,mask,lengths,chain_M,chain_encoding,chain_list,visible,masked,masked_lengths,chain_pos,omit_mask,residue_idx,dihedral,tied,pssm_coef,pssm_bias,pssm_odds,bias_by_res,tied_beta=features
    rows=[]
    with torch.inference_mode():
        for i in range(request['count']):
            noise=torch.randn(chain_M.shape,device=device)
            sample=model.sample(X,noise,S,chain_M,chain_encoding,residue_idx,mask=mask,temperature=request['temperature'],
                omit_AAs_np=np.array([0.]*20+[1.],dtype=np.float32),bias_AAs_np=np.zeros(21,dtype=np.float32),
                chain_M_pos=chain_pos,omit_AA_mask=omit_mask,pssm_coef=pssm_coef,pssm_bias=pssm_bias,pssm_multi=0,
                pssm_log_odds_flag=False,pssm_log_odds_mask=pssm_odds>0,pssm_bias_flag=False,bias_by_res=bias_by_res)
            seq=sample['S']
            probs=model(X,seq,mask,chain_M*chain_pos,residue_idx,chain_encoding,noise,use_input_decoding_order=True,decoding_order=sample['decoding_order'])
            score=float(_scores(seq,probs,mask*chain_M*chain_pos).item())
            rows.append({'name':'design_'+str(i+1),'sequence':_S_to_seq(seq[0],mask[0]),'model_negative_log_likelihood':score})
    print('PORTAL_PROTEIN='+json.dumps({'model':'ProteinMPNN v_48_020','revision':REVISION,'sequences':rows},allow_nan=False),flush=True)


REVISION='8907e6671bfbfc92303b5f79c4b5e6ce47cdef57'
if __name__=='__main__':main()
