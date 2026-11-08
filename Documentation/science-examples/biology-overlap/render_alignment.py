"""Scientific figure drawn from the saved MAFFT alignment, not a GUI mockup."""
from pathlib import Path
import json, textwrap
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyArrow

HERE=Path(__file__).resolve().parent
def read_fasta(path):
    rows={}; key=None
    for line in path.read_text().splitlines():
        if line.startswith('>'):key=line[1:];rows[key]=''
        elif key:rows[key]+=line.strip().upper()
    return rows
r=json.loads((HERE/'validation.json').read_text())
seqs=read_fasta(HERE/'mafft-alignment.fasta')
bg='#f3efe5';ink='#27393b';teal='#297f88';gold='#ceab5e'
fig=plt.figure(figsize=(16,10),facecolor=bg)
fig.text(.05,.945,'OVERLAP ASSEMBLY · REAL TOOL OUTPUT',fontsize=13,color=teal,weight='bold')
fig.text(.05,.89,'Three fragments. One verified sequence.',fontsize=28,color=ink,weight='bold')
fig.text(.05,.845,'310 input bases  −  2 × 35-base overlaps  =  240 bases',fontsize=19,color=ink)
ax=fig.add_axes([.13,.60,.80,.20],facecolor=bg)
for a,b in ((75,110),(145,180)):ax.axvspan(a,b,color=gold,alpha=.25)
for i,(name,start,end,direction) in enumerate([('A',0,110,1),('B',75,180,-1),('C',145,240,1)]):
    y=2-i
    ax.add_patch(FancyArrow(start if direction==1 else end,y,(end-start)*direction,0,width=.26,head_width=.5,head_length=5,length_includes_head=True,color=teal))
    ax.text(-8,y,f'{name}  {"+" if direction==1 else "RC"}',ha='right',va='center',fontsize=14,color=ink,weight='bold')
ax.set_xlim(-3,243);ax.set_ylim(-.65,2.6);ax.set_yticks([]);ax.set_xticks([0,75,110,145,180,240]);ax.tick_params(labelsize=11,colors=ink)
for spine in ax.spines.values():spine.set_visible(False)
ax.set_xlabel('Position in assembled sequence · 0-based coordinates',fontsize=11,color=ink)
fig.text(.05,.545,'MAFFT verification',fontsize=18,color=ink,weight='bold')
fig.text(.05,.51,'B was reverse-complemented. Every aligned base agrees; each overlap occurs once in the final sequence.',fontsize=12,color=ink)
items=list(seqs.items());ordered=[items[1],items[2],items[3],items[0]]
labels=['A +','B RC','C +','Result']
for block in range(4):
    x=.05 if block%2==0 else .535;y=.445-(block//2)*.19
    fig.text(x,y,f'BASES {block*60+1}–{(block+1)*60}',fontsize=11,weight='bold',color=teal)
    for j,((name,seq),label) in enumerate(zip(ordered,labels)):
        fig.text(x,y-.033*(j+1),f'{label:6s} {seq[block*60:(block+1)*60]}',fontfamily='DejaVu Sans Mono',fontsize=9.2,color=ink,weight='bold' if j==3 else 'normal')
fig.text(.05,.065,'Synthetic teaching DNA · exact-overlap discovery → PortalAI assembly → MAFFT verification → held-out reference check',fontsize=11,color=ink)
fig.text(.05,.035,'Reproducible script-run report, not an autonomous Nice chat or a built-in GUI panel. MAFFT is a verifier here, not the assembler.',fontsize=10,color='#646e6d')
fig.savefig(HERE/'overlap-alignment.png',dpi=130,facecolor=bg)
fig.savefig(HERE/'overlap-alignment.svg',facecolor=bg)
print(HERE/'overlap-alignment.png')
