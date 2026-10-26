"""Bounded, host-neutral biology calculations. No network, files or code evaluation."""
from __future__ import annotations
import hashlib
import html
import io
import itertools
import math
import re

DNA = set('ACGT')
AA = set('ACDEFGHIKLMNPQRSTVWY')
SITES = {'EcoRI':'GAATTC', 'XbaI':'TCTAGA', 'SpeI':'ACTAGT', 'PstI':'CTGCAG',
         'BsaI':'GGTCTC', 'BsmBI':'CGTCTC'}


def number(value, name, low=0, high=1e9):
    if isinstance(value, bool): raise ValueError(name+' must be numeric')
    v=float(value)
    if not math.isfinite(v) or not low <= v <= high: raise ValueError(name+' is outside its finite bounds')
    return v


def integer(value, name, low, high):
    n=number(value,name,low,high)
    if n!=int(n): raise ValueError(name+' must be an integer')
    return int(n)


def sequence(value, alphabet=DNA, maximum=200000):
    if not isinstance(value,str): raise ValueError('sequence must be a string')
    seq=''.join(value.split()).upper()
    if not seq or len(seq)>maximum or set(seq)-alphabet:
        raise ValueError('Sequence is empty, too long, or contains unsupported symbols (FASTA headers are not sequences)')
    return seq


def reverse(seq):
    return seq.translate(str.maketrans('ACGT','TGCA'))[::-1]


def sites(seq, circular=False):
    out=[]
    for name,motif in SITES.items():
        text=seq+((seq*len(motif))[:len(motif)-1] if circular else '')
        for strand,pattern in ((1,motif),(-1,reverse(motif))):
            if strand==-1 and pattern==motif: continue
            for match in re.finditer('(?='+pattern+')',text):
                if match.start()<len(seq): out.append({'enzyme':name,'start':match.start(),'strand':strand})
    return out


def assemble(p, check=lambda:None):
    from Bio.Seq import Seq
    from Bio.SeqRecord import SeqRecord
    from Bio.SeqFeature import SeqFeature, FeatureLocation, CompoundLocation
    from Bio import SeqIO
    parts=p.get('parts')
    if not isinstance(parts,list) or not 1<=len(parts)<=64: raise ValueError('Provide 1..64 ordered parts')
    method=p.get('method','annotated_join')
    if method not in ('annotated_join','biobrick_rfc10','overlap'): raise ValueError('Unknown assembly method')
    circular=p.get('circular',False)
    if not isinstance(circular,bool): raise ValueError('circular must be boolean')
    if circular and sum(x.get('role')=='backbone' for x in parts)!=1:
        raise ValueError('A circular plasmid requires exactly one explicit backbone part')
    if circular and method=='biobrick_rfc10':
        raise ValueError('RFC10 builds an unflanked linear insert cassette; provide a vector-specific cloning plan separately')
    oriented=[];names=set()
    for part in parts:
        name=part.get('name')
        if not isinstance(name,str) or not 1<=len(name)<=100 or name in names: raise ValueError('Part names must be unique, 1..100 characters')
        names.add(name);s=sequence(part['sequence'])
        strand=part.get('strand',1)
        if isinstance(strand,bool) or strand not in (-1,1): raise ValueError('strand must be 1 or -1')
        if strand==-1:s=reverse(s)
        if method=='biobrick_rfc10' and any(row['enzyme'] in ('EcoRI','XbaI','SpeI','PstI') for row in sites(s)):
            raise ValueError('RFC10 core parts must exclude prefix/suffix and internal EcoRI/XbaI/SpeI/PstI sites')
        oriented.append((part,s,strand))
    if sum(len(s) for _,s,_ in oriented)>200000: raise ValueError('Assembly exceeds 200,000 input bases')
    overlaps=p.get('overlaps',[])
    if method=='overlap' and (not isinstance(overlaps,list) or len(overlaps)!=len(parts)-1+int(circular)):
        raise ValueError('overlaps needs one length for each adjacent junction, plus the closing junction if circular')
    result='';features=[];junctions=[]
    for i,(part,s,strand) in enumerate(oriented):
        check();start=len(result)
        if i and method=='biobrick_rfc10':
            junctions.append({'start':len(result),'sequence':'TACTAGAG','kind':'RFC10 scar'})
            result+='TACTAGAG';start=len(result)
        elif i and method=='overlap':
            n=integer(overlaps[i-1],'overlap',12,min(len(oriented[i-1][1]),len(s))-1)
            if result[-n:]!=s[:n]:raise ValueError('Adjacent fragments do not match the requested overlap')
            junctions.append({'start':len(result)-n,'sequence':s[:n],'kind':'exact overlap'})
            start-=n;s=s[n:]
        result+=s
        features.append({'name':part['name'],'role':str(part.get('role','part'))[:100],
                         'start':start,'end':len(result),'strand':strand,'source':str(part.get('source','user supplied'))[:500]})
    if circular and method=='overlap':
        n=integer(overlaps[-1],'closing overlap',12,min(len(oriented[-1][1]),len(oriented[0][1]))-1)
        if result[-n:]!=result[:n]:raise ValueError('Circular closing overlap does not match')
        result=result[:-n]
        if any(f['end']>len(result)*2 or f['start']>=len(result) for f in features):raise ValueError('Overlaps consume a whole fragment')
    n=len(result)
    record=SeqRecord(Seq(result),id='assembly',name='assembly',description='PortalAI in-silico assembly; experimental validation required')
    record.annotations={'molecule_type':'DNA','topology':'circular' if circular else 'linear'}
    for f in features:
        intervals=[(f['start'],min(f['end'],n))]
        if f['end']>n:intervals.append((0,f['end']-n))
        locations=[FeatureLocation(a,b,strand=f['strand']) for a,b in intervals]
        location=locations[0] if len(locations)==1 else CompoundLocation(locations if f['strand']==1 else locations[::-1])
        record.features.append(SeqFeature(location,type='misc_feature',qualifiers={'label':[f['name']], 'note':[f['role'],f['source']]}))
    gb=io.StringIO();SeqIO.write(record,gb,'genbank')
    data={'length_bp':n,'sequence':result,'sha256':hashlib.sha256(result.encode()).hexdigest(),
          'topology':record.annotations['topology'],'method':method,'features':features,'junctions':junctions,
          'restriction_sites':sites(result,circular),'coordinates':'0-based, half-open; end > length wraps the origin',
          'limitations':['Annotated joins require user-supplied junction chemistry.',
              'RFC10 eight-base scars are not frame-preserving protein fusion junctions.',
              'Sequence compatibility does not establish expression, vector replication or experimental success.']}
    return data,{'assembly.gb':gb.getvalue(),'assembly.fasta':'>assembly\n'+result+'\n','assembly.svg':feature_svg(features,n)}


def feature_svg(features,length):
    width=1100; height=100+min(len(features),100)*30
    chunks=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
            '<rect width="100%" height="100%" fill="#fff"/>',
            f'<text x="20" y="28" font-family="sans-serif">Linearized map: {length} bases; coordinates 0-based, half-open</text>']
    for i,f in enumerate(features[:100]):
        y=60+i*30
        chunks.append(f'<text x="20" y="{y+12}" font-size="12" font-family="sans-serif">{html.escape(f["name"][:24])}</text>')
        a=f['start'];b=f['end']
        for left,right in [(a,min(b,length))]+([(0,b-length)] if b>length else []):
            x=240+820*left/length;w=max(1,820*(right-left)/length)
            chunks.append(f'<rect x="{x:.2f}" y="{y}" width="{w:.2f}" height="18" fill="#397f83"><title>{html.escape(f["name"])} {a}:{b} strand {f["strand"]}</title></rect>')
    return ''.join(chunks)+'</svg>'


def genome_features(p,check=lambda:None):
    from Bio import SeqIO
    text=p['text']
    if not isinstance(text,str) or len(text)>4*1024**2:raise ValueError('GenBank text must be at most 4 MiB')
    record=SeqIO.read(io.StringIO(text),'genbank')
    if len(record)>2_000_000 or len(record.features)>10000:raise ValueError('Region is too large; select a smaller record')
    start=integer(p.get('start',0),'start',0,max(0,len(record)-1))
    end=integer(p.get('end',len(record)),'end',start+1,len(record))
    rows=[]
    for f in record.features:
        check()
        if f.location is None:continue
        # Keep compound segments and fuzzy positions; do not flatten exon joins into a contiguous feature.
        segments=[{'start':int(s.start),'end':int(s.end),'strand':s.strand} for s in f.location.parts]
        if not any(s['start']<end and s['end']>start for s in segments):continue
        rows.append({'type':f.type,'location':str(f.location),'segments':segments,
                     'qualifiers':{k:v for k,v in f.qualifiers.items() if k in ('gene','locus_tag','product','label','note','protein_id')}})
    return {'id':record.id,'description':record.description,'length_bp':len(record),'region':[start,end],
            'sequence':str(record.seq[start:end]),'features':rows,'coordinates':'0-based half-open; original compound/fuzzy locations retained'}


def protein_variants(p,check=lambda:None):
    from Bio.SeqUtils.ProtParam import ProteinAnalysis
    reference=sequence(p['sequence'],AA,10000)
    variants=p.get('variants',[])
    if not isinstance(variants,list) or len(variants)>64:raise ValueError('At most 64 variants')
    rows=[]
    for entry in [{'name':'reference','substitutions':[]},*variants]:
        check();seq=list(reference);seen=set()
        edits=entry.get('substitutions',[])
        if not isinstance(edits,list) or len(edits)>100:raise ValueError('At most 100 substitutions per variant')
        for mutation in edits:
            m=re.fullmatch(r'([ACDEFGHIKLMNPQRSTVWY])([1-9][0-9]*)([ACDEFGHIKLMNPQRSTVWY])',str(mutation))
            if not m:raise ValueError('Use substitutions like A12G, with 1-based positions')
            old,pos,new=m.group(1),int(m.group(2))-1,m.group(3)
            if pos>=len(seq) or reference[pos]!=old or pos in seen:raise ValueError('Substitution reference/position is invalid or repeated')
            seen.add(pos);seq[pos]=new
        seq=''.join(seq);analysis=ProteinAnalysis(seq)
        rows.append({'name':str(entry.get('name','variant'))[:100],'sequence':seq,'substitutions':edits,
                     'molecular_weight_da':analysis.molecular_weight(),'isoelectric_point':analysis.isoelectric_point(),
                     'gravy':analysis.gravy(),'aromaticity':analysis.aromaticity(),
                     'instability_index':analysis.instability_index() if len(seq)>1 else None})
    return {'variants':rows,'limitations':['Sequence descriptors are not predictions of folding, potency, solubility, safety or production yield.']}


def rank_parts(p,check=lambda:None):
    parts=p.get('parts',[])
    if not isinstance(parts,list) or not 1<=len(parts)<=500:raise ValueError('Provide 1..500 characterized parts')
    required=('host','condition','role','metric','unit')
    for k in required:
        if not isinstance(p.get(k),str) or not p[k].strip():raise ValueError('Part ranking requires explicit '+k)
    target=number(p['target'],'target',-1e12,1e12)
    rows=[];excluded=[]
    for part in parts:
        check()
        if any(part.get(k)!=p[k] for k in required) or not part.get('source'):
            excluded.append(str(part.get('name','unnamed')));continue
        value=number(part['value'],'measured value',-1e12,1e12)
        rows.append({**part,'absolute_distance_to_target':abs(value-target)})
    rows.sort(key=lambda r:r['absolute_distance_to_target'])
    return {'ranked':rows,'excluded':excluded,'target':target,'selection_basis':{k:p[k] for k in required},
            'limitations':['Ranks supplied comparable measurements only. RBS/promoter/terminator effects depend on host, sequence context and measurement conditions; no universal strength score is inferred.']}


def circuit(p,check=lambda:None):
    import numpy as np
    from scipy.integrate import solve_ivp
    genes=p.get('genes',[])
    if not isinstance(genes,list) or not 1<=len(genes)<=12:raise ValueError('Provide 1..12 genes with explicit kinetic parameters')
    names=[g['name'] for g in genes]
    if any(not isinstance(n,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,39}',n) for n in names) or len(set(names))!=len(names):
        raise ValueError('Gene names must be unique identifiers')
    duration=number(p['duration'],'duration',1e-8,1e5)
    points=integer(p.get('points',101),'points',2,1001)
    rates=[];initial=[]
    for g in genes:
        rates.append([number(g[k],k,0,1e4) for k in ('transcription','translation','mrna_decay','protein_decay')])
        initial.extend([number(g.get('initial_mrna',0),'initial_mrna'),number(g.get('initial_protein',0),'initial_protein')])
        for edge in g.get('regulators',[]):
            if edge.get('gene') not in names or edge.get('mode') not in ('activate','repress'):raise ValueError('Unknown regulator or Hill mode')
            number(edge['K'],'K',1e-9,1e9);number(edge.get('n',1),'Hill n',.1,8)
        if len(g.get('regulators',[]))>12:raise ValueError('Too many regulators')
    dilution=number(p.get('dilution',0),'dilution',0,1e4)
    rtol=number(p.get('rtol',1e-6),'rtol',1e-10,.01);atol=number(p.get('atol',1e-9),'atol',1e-12,.01)
    calls=0
    def rhs(t,y):
        nonlocal calls
        calls+=1
        if calls>50000:raise RuntimeError('Circuit exceeded 50,000 solver evaluations; revise timescale/parameters')
        check();out=[]
        for i,g in enumerate(genes):
            factor=1.
            for edge in g.get('regulators',[]):
                x=max(0,float(y[2*names.index(edge['gene'])+1]))
                n=float(edge.get('n',1));K=float(edge['K'])
                h=(x/K)**n;factor*=h/(1+h) if edge['mode']=='activate' else 1/(1+h)
            leak=number(g.get('leak_fraction',0),'leak_fraction',0,1)
            a,b,dm,dp=rates[i];m,protein=y[2*i:2*i+2]
            out.extend([a*(leak+(1-leak)*factor)-(dm+dilution)*m,b*m-(dp+dilution)*protein])
        return out
    sol=solve_ivp(rhs,[0,duration],initial,t_eval=np.linspace(0,duration,points),rtol=rtol,atol=atol,method='LSODA')
    if not sol.success or not np.isfinite(sol.y).all():raise RuntimeError('Circuit integration did not converge')
    return {'time':sol.t.tolist(),'trajectories':{name:{'mrna':sol.y[2*i].tolist(),'protein':sol.y[2*i+1].tolist()} for i,name in enumerate(names)},
            'solver':'LSODA','rtol':rtol,'atol':atol,'evaluations':calls,
            'units':'User-supplied consistent time and concentration units; no automatic unit conversion',
            'limitations':['Deterministic Hill model; regulator effects multiply. No resource burden, stochasticity, metabolic coupling or experimentally calibrated yield unless supplied by the modeler.']}


def bioprocess(p,check=lambda:None):
    import numpy as np
    from scipy.integrate import solve_ivp
    # Units: h, L, g/L; mu_max /h, Ks g/L, yield g biomass/g substrate.
    mu=number(p['mu_max'],'mu_max',0,10);ks=number(p['Ks'],'Ks',1e-9,1e4)
    yield_xs=number(p['yield_xs'],'yield_xs',1e-9,10)
    alpha=number(p.get('alpha',0),'alpha',0,1e3);beta=number(p.get('beta',0),'beta',0,1e3)
    feed=number(p.get('feed_l_h',0),'feed_l_h',0,1e6);sf=number(p.get('feed_substrate_g_l',0),'feed_substrate_g_l',0,1e4)
    death=number(p.get('death_h',0),'death_h',0,10)
    initial=[number(p[k],k,0,1e4) for k in ('biomass_g_l','substrate_g_l','product_g_l')]+[number(p['volume_l'],'volume_l',1e-6,1e6)]
    duration=number(p['duration_h'],'duration_h',1e-6,1000);points=integer(p.get('points',101),'points',2,1001)
    rtol=number(p.get('rtol',1e-7),'rtol',1e-10,.01);atol=number(p.get('atol',1e-9),'atol',1e-12,.01)
    calls=0
    def rhs(t,y):
        nonlocal calls
        calls+=1
        if calls>50000:raise RuntimeError('Bioprocess solver evaluation limit exceeded')
        check();x,s,product,v=y;growth=mu*max(s,0)/(ks+max(s,0));d=feed/v
        return [(growth-death-d)*x,-growth*x/yield_xs+d*(sf-s),(alpha*growth+beta)*x-d*product,feed]
    sol=solve_ivp(rhs,[0,duration],initial,t_eval=np.linspace(0,duration,points),rtol=rtol,atol=atol,method='LSODA')
    if not sol.success or not np.isfinite(sol.y).all():raise RuntimeError('Bioprocess integration did not converge')
    return {'time_h':sol.t.tolist(),**{k:sol.y[i].tolist() for i,k in enumerate(('biomass_g_l','substrate_g_l','product_g_l','volume_l'))},
            'solver':'LSODA','rtol':rtol,'atol':atol,
            'limitations':['Monod growth and Luedeking-Piret phenomenological product model. Product formation is not a substrate/elemental balance. Oxygen, inhibition, maintenance, secretion and product quality are not modeled. Not an automatic commercial process optimizer.']}


OPERATIONS={'plasmid.assemble':assemble,'genome.features':genome_features,'protein.variants':protein_variants,
            'parts.rank':rank_parts,'circuit.simulate':circuit,'bioprocess.simulate':bioprocess}
