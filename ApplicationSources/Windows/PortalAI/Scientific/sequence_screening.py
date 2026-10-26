"""Local reference scans with explicit coverage, mismatch and annotation semantics."""
import hashlib,io,json,os,re
from Scientific.extensions_common import integer,keys,read
DNA=set('ACGT');AMBIG=set('ACGTRYSWKMBDHVN')
TRANS=str.maketrans('ACGTRYSWKMBDHVN','TGCAYRSWMKVHDBN')
def rc(s):return s.translate(TRANS)[::-1]
def dna(s,low=15,high=80):
    if not isinstance(s,str):raise ValueError('DNA sequence must be text')
    s=''.join(s.split()).upper()
    if not low<=len(s)<=high or set(s)-DNA:raise ValueError(f'DNA requires {low}..{high} unambiguous A/C/G/T bases')
    return s

def hits(text,query,mismatches,check):
    """Pigeonhole seeds enumerate every substitution-only match, without indels."""
    n=len(query);candidates=set()
    for part in range(mismatches+1):
        left=n*part//(mismatches+1);right=n*(part+1)//(mismatches+1);seed=query[left:right];at=0
        while True:
            at=text.find(seed,at)
            if at<0:break
            start=at-left;at+=1
            if 0<=start<=len(text)-n:candidates.add(start)
            if len(candidates)>250000:raise ValueError('Repetitive reference exceeded candidate budget; use a more specific query or indexed aligner')
        check()
    for i,start in enumerate(sorted(candidates)):
        if i%2048==0:check()
        target=text[start:start+n]
        if set(target)-DNA:continue
        diff=[j+1 for j,(a,b) in enumerate(zip(query,target)) if a!=b]
        if len(diff)<=mismatches:yield start,diff

def fasta_blocks(path,overlap,check,block=1024*1024):
    """Stream full FASTA; bounded line/chunk memory. Keep contig-relative coordinates."""
    digest=hashlib.sha256();total=0;name=None;sequence='';offset=0;seen=set();ambiguous=0;line_count=0
    with path.open('rb') as f:
        before=os.fstat(f.fileno())
        if before.st_size>6*1024**3:raise ValueError('Reference exceeds 6 GiB')
        while True:
            raw=f.readline(2*1024**2)
            if not raw:break
            if len(raw)>=2*1024**2:raise ValueError('FASTA line exceeds 2 MiB; wrap lines before analysis')
            digest.update(raw);line_count+=1
            if line_count%1024==0:check()
            line=raw.decode('ascii').strip()
            if not line:continue
            if line.startswith('>'):
                if name is not None and sequence:yield name,offset,sequence,True,None
                name=line[1:].split()[0]
                if not name or name in seen or len(name)>200:raise ValueError('FASTA needs unique bounded contig IDs')
                seen.add(name);sequence='';offset=0
                if len(seen)>100000:raise ValueError('Too many FASTA contigs')
            else:
                if name is None:raise ValueError('Reference must be FASTA')
                line=line.upper()
                if set(line)-AMBIG:raise ValueError('Invalid DNA character in FASTA')
                total+=len(line);ambiguous+=sum(c not in DNA for c in line);sequence+=line
                if len(sequence)>=block+overlap:
                    yield name,offset,sequence,False,None
                    advance=len(sequence)-2*overlap;offset+=advance;sequence=sequence[-2*overlap:]
        if name is not None and sequence:yield name,offset,sequence,True,None
        after=os.fstat(f.fileno())
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
    if identity(before)!=identity(after) or before.st_ctime_ns!=after.st_ctime_ns or identity(after)!=identity(path.stat()):raise RuntimeError('Reference changed during scan')
    if total==0:raise ValueError('Empty reference')
    yield None,0,'',True,{'reference_sha256':digest.hexdigest(),'reference_bases':total,'contigs':len(seen),'ambiguous_reference_bases':ambiguous,'unambiguous_windows_only':True}

def specificity(p,context):
    keys(p,{'reference','queries','mismatches','primer_pair','max_amplicon'})
    from media_paths import media_reference
    entries=p['queries']
    if not isinstance(entries,list) or not 1<=len(entries)<=8:raise ValueError('Supply 1..8 named queries')
    queries=[];names=set()
    for entry in entries:
        if set(entry)-{'name','sequence','pam'}:raise ValueError('Query fields are name, sequence, optional 3-prime PAM')
        name=entry['name'];seq=dna(entry['sequence']);pam=entry.get('pam','').upper()
        if not isinstance(name,str) or not 1<=len(name)<=80 or name in names:raise ValueError('Queries need unique names')
        if len(pam)>8 or set(pam)-AMBIG:raise ValueError('PAM must be <=8 IUPAC DNA bases')
        names.add(name);queries.append((name,seq,pam))
    mm=integer(p.get('mismatches',2),'mismatches',0,3);overlap=max(len(s)+len(pam)*2 for _,s,pam in queries)
    iupac={'A':'A','C':'C','G':'G','T':'T','R':'AG','Y':'CT','S':'GC','W':'AT','K':'GT','M':'AC','B':'CGT','D':'AGT','H':'ACT','V':'ACG','N':'ACGT'}
    rows=[];seen=set();coverage=None
    path=media_reference(context.root,p['reference'])
    for contig,offset,text,last,info in fasta_blocks(path,overlap,context.check):
        if info is not None:coverage=info;continue
        for name,seq,pam in queries:
            for strand,q in (('+',seq),('-',rc(seq))):
                for at,diff in hits(text,q,mm,context.check):
                    if not last and at>=len(text)-overlap:continue
                    key=(contig,offset+at,name,strand)
                    if key in seen:continue
                    # Reverse-strand PAM is upstream on the forward reference.
                    observed=text[at+len(q):at+len(q)+len(pam)] if strand=='+' else rc(text[max(0,at-len(pam)):at])
                    if pam and (len(observed)!=len(pam) or any(c not in iupac[d] for c,d in zip(observed,pam))):continue
                    seen.add(key);rows.append({'query':name,'contig':contig,'start':offset+at,'end':offset+at+len(q),'strand':strand,'mismatches':len(diff),'mismatch_query_positions':diff if strand=='+' else sorted(len(q)+1-d for d in diff),'pam':observed})
                    if len(rows)>10000:raise ValueError('More than 10000 matches; query is too repetitive for this bounded report')
    products=[]
    if p.get('primer_pair'):
        pair=p['primer_pair']
        if not isinstance(pair,list) or len(pair)!=2 or len(set(pair))!=2 or not set(pair)<=names:raise ValueError('primer_pair needs two distinct query names')
        maximum=integer(p.get('max_amplicon',5000),'max_amplicon',20,100000)
        lefts=[r for r in rows if r['query'] in pair and r['strand']=='+'];rights=[r for r in rows if r['query'] in pair and r['strand']=='-']
        if len(lefts)*len(rights)>2000000:raise ValueError('Primer pairing exceeds comparison budget')
        for left in lefts:
            context.check()
            for right in rights:
                if left['query']!=right['query'] and left['contig']==right['contig'] and left['end']<=right['start'] and right['end']-left['start']<=maximum:
                    products.append({'contig':left['contig'],'start':left['start'],'end':right['end'],'length':right['end']-left['start'],'left_query':left['query'],'right_query':right['query']})
                    if len(products)>10000:raise ValueError('Too many primer products')
    return {**coverage,'coverage_complete':True,'coordinates':'0-based half-open on forward reference','maximum_substitutions':mm,'hits':rows,'primer_products':products,'limitations':['Only the supplied FASTA was scanned. Missing assemblies/variants and ambiguous bases are not cleared.','Substitution-only matches on both strands; no bulges/indels, thermodynamic PCR model, chromatin or cleavage probability. PAM is optional and 3-prime only.','Timeout or resource exhaustion fails the operation; a partial scan is never reported as specificity clearance.']},{}

def annotate(p,context):
    if p.get('engine')=='plannotate' or ('features' not in p and p.get('engine')!='exact'):
        from Scientific.plannotate_tool import run
        return run(p,context)
    p=dict(p);engine=p.pop('engine','exact')
    if engine!='exact':raise ValueError('engine must be exact or plannotate')
    keys(p,{'sequence','file','features','circular','name'})
    from Bio import SeqIO
    from Bio.Seq import Seq
    from Bio.SeqRecord import SeqRecord
    from Bio.SeqFeature import SeqFeature,FeatureLocation,CompoundLocation
    if ('sequence' in p)==('file' in p):raise ValueError('Supply sequence or one FASTA file')
    seq=dna(p['sequence'],1,2000000) if 'sequence' in p else dna(str(SeqIO.read(io.StringIO(read(context,p['file'],4*1024**2).decode()),'fasta').seq),1,2000000)
    features=p['features']
    if not isinstance(features,list) or not 1<=len(features)<=128:raise ValueError('Supply 1..128 reference features with name, sequence, role and source')
    circular=p.get('circular',False)
    if not isinstance(circular,bool):raise ValueError('circular must be boolean')
    rec=SeqRecord(Seq(seq),id='annotated',description=str(p.get('name','Reference annotation'))[:120]);rec.annotations={'molecule_type':'DNA','topology':'circular' if circular else 'linear'};rows=[]
    for f in features:
        context.check()
        if set(f)!={'name','sequence','role','source'} or not all(isinstance(f[k],str) and 1<=len(f[k])<=500 for k in ('name','role','source')):raise ValueError('Each feature needs bounded name, sequence, role, source')
        query=dna(f['sequence'],6,min(100000,len(seq)));text=seq+seq[:len(query)-1] if circular else seq
        for strand,q in ((1,query),(-1,rc(query))):
            start=0
            while True:
                start=text.find(q,start)
                if start<0 or start>=len(seq):break
                end=start+len(q);pieces=[FeatureLocation(start,min(end,len(seq)),strand=strand)]
                if end>len(seq):pieces.append(FeatureLocation(0,end-len(seq),strand=strand))
                location=pieces[0] if len(pieces)==1 else CompoundLocation(pieces if strand==1 else pieces[::-1])
                rec.features.append(SeqFeature(location,type='misc_feature',qualifiers={'label':[f['name']],'note':[f['role']],'inference':['exact match to supplied reference: '+f['source']]}))
                rows.append({'name':f['name'],'role':f['role'],'source':f['source'],'start':start,'end_unwrapped':end,'strand':strand,'identity':1.0});start+=1
                if len(rows)>10000:raise ValueError('Too many feature matches')
    out=io.StringIO();SeqIO.write(rec,out,'genbank')
    return {'features':rows,'length':len(seq),'circular':circular,'coordinates':'0-based half-open; circular ends may exceed length','limitations':['Exact supplied-reference annotation, including reverse strand and circular junctions. Not pLannotate, de novo gene/function discovery or a whole-genome annotation pipeline.','Missing features mean no exact match to this catalog, not biological absence. Reference labels are attributed, not independently verified.']},{'annotated.gb':out.getvalue()}
