"""Reproducible arbitrary-DNA demonstration; never consult expected.fasta to assemble."""
import argparse, itertools, json, hashlib, subprocess, sys, os
from pathlib import Path

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--portalai-root',required=True,type=Path)
parser.add_argument('--mafft',required=True,type=Path)
parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parent)
args=parser.parse_args()
HERE=args.output.resolve()
root=args.portalai_root.resolve()
for candidate in (root/'Runtime/ScientificPython/packages',root/'Runtime/SciencePackages',root/'Runtime/LinuxPackages/science'):
    if (candidate/'Bio').is_dir():sys.path.insert(0,str(candidate));break
sys.path.insert(0,str(root))
from Bio import SeqIO
from Scientific import biology

fragments={r.id:str(r.seq).upper() for r in SeqIO.parse(HERE/'fragments.fasta','fasta')}
def overlap(a,b):
    return next((n for n in range(min(len(a),len(b))-1,19,-1) if a[-n:]==b[:n]),0)

candidates=[]
for order in itertools.permutations(fragments):
    for strands in itertools.product((1,-1), repeat=len(order)):
        if strands[order.index('fragment_A')]!=1: continue # orientation anchor only
        oriented=[fragments[k] if s==1 else biology.reverse(fragments[k]) for k,s in zip(order,strands)]
        joins=[overlap(a,b) for a,b in zip(oriented,oriented[1:])]
        if all(joins): candidates.append((order,strands,oriented,joins))
assert len(candidates)==1, f'Ambiguous or disconnected exact-overlap graph: {len(candidates)}'
order,strands,oriented,joins=candidates[0]
request={'method':'overlap','circular':False,'overlaps':joins,'parts':[{'name':k,'sequence':fragments[k],'strand':s,'role':'arbitrary synthetic teaching fragment','source':'fragments.fasta'} for k,s in zip(order,strands)]}
result, files=biology.assemble(request)
for name,text in files.items(): (HERE/name).write_text(text)
(HERE/'assembly-request.json').write_text(json.dumps(request,indent=2))
(HERE/'assembly-result.json').write_text(json.dumps(result,indent=2))
(HERE/'oriented-fragments.fasta').write_text(''.join(f'>{k}_strand_{s:+d}\n{seq}\n' for k,s,seq in zip(order,strands,oriented)))
mafft=args.mafft.resolve()
args=[str(mafft),'--nuc','--auto','--thread','2','--addfragments',str(HERE/'oriented-fragments.fasta'),'--keeplength',str(HERE/'assembly.fasta')]
command=['cmd.exe','/d','/s','/c',subprocess.list2cmdline(args)] if os.name=='nt' and mafft.suffix.lower()=='.bat' else args
p=subprocess.run(command,cwd=HERE,text=True,capture_output=True,timeout=180)
assert p.returncode==0,p.stderr[-1000:]
(HERE/'mafft-alignment.fasta').write_text(p.stdout)
(HERE/'mafft-log.txt').write_text(p.stderr)
alignment=list(SeqIO.parse(HERE/'mafft-alignment.fasta','fasta'))
assert len(alignment)==4
assert str(alignment[0].seq).upper()==result['sequence']
positions=[]
for row,(k,s,seq),feature in zip(alignment[1:],zip(order,strands,oriented),result['features']):
    aligned=str(row.seq).upper()
    assert len(aligned)==result['length_bp']
    assert aligned.replace('-','')==seq
    occupied=[i for i,c in enumerate(aligned) if c!='-']
    assert occupied==list(range(feature['start'],feature['end']))
    assert all(c=='-' or c==result['sequence'][i] for i,c in enumerate(aligned))
    positions.append({'name':k,'strand':s,'start':occupied[0],'end':occupied[-1]+1})
# Held-out truth is consulted only after assembly and MAFFT verification.
expected=str(next(SeqIO.parse(HERE/'expected.fasta','fasta')).seq)
assert result['sequence']==expected
assert sum(map(len,fragments.values()))-sum(joins)==len(expected)
receipt={'order':list(order),'strands':list(strands),'overlaps':joins,'input_bp':sum(map(len,fragments.values())),'output_bp':len(expected),'duplicate_overlap_bp_removed':sum(joins),'matches_held_out_reference':True,'mafft':'7.526','mafft_command':['mafft','--nuc','--auto','--thread','2','--addfragments','oriented-fragments.fasta','--keeplength','assembly.fasta'],'aligned_positions':positions,'provenance':'Executed reproducible Python workflow using unmodified PortalAI biology.assemble plus official MAFFT. Not a new autonomous Nice chat run; exact-overlap discovery is in this example script, not a new GUI feature.'}
(HERE/'validation.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt,indent=2))
