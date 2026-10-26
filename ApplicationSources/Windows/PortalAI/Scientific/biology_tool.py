"""Profile-bound biology routing, public database retrieval and immutable exports."""
from pathlib import Path
import hashlib
import json
import os
import re
import time
import uuid
from urllib.parse import urlencode, urlparse
from Scientific import biology

HELP = {
 'plasmid.assemble':'parts:[{name,sequence,role,strand,source}], method:annotated_join|biobrick_rfc10|overlap, circular:false, overlaps:[lengths]. Exports GenBank/FASTA/SVG.',
 'genome.features':'text:one GenBank record (or file:path); optional start/end:0-based half-open region. Keeps joined/fuzzy feature locations.',
 'protein.variants':'sequence:reference amino acids, variants:[{name,substitutions:[A12G]}]. Sequence descriptors; not activity predictions.',
 'protein.design':'Required science input: {"pdb":"attached/local/file.pdb","chain":"A"}. PDB is text. One complete, consecutive 8..256-residue chain; file <=2 MiB. Optional count:1..8, temperature:0.05..1, seed:1..2147483647, fixed_positions:[1-based observed residues]. CPU ProteinMPNN fixed-backbone sequences; no PAM/binding/function optimization. Do not rename pdb to structure/file.',
 'protein.inspect':'file:attached/local PDB or mmCIF path (legacy input:path accepted), optional chain:author chain ID, model_index:0-based default 0. CPU analysis <=20 MiB / 200000 atoms; chains, sequences, numbering gaps, incomplete backbones, other residues. Exports full structure.json and declared/observed FASTA. Declared sequence is from this file, not necessarily wild type.',
 'protein.structure_variants':'file:PDB/mmCIF path, chain:explicit author ID, sequence_source:declared(default)|observed, variants:[{name:candidate,substitutions:[A12G]}] (1..8). Substitutions use 1-based selected SEQUENCE positions, NOT author residue numbers. Exports reference/candidate FASTA and descriptor/change JSON. Explicit sequence edits only; no rebuilt structure, folding or PAM/activity prediction. Run protein.inspect first; missing/ambiguous sequence fails, never silently substitutes.',
 'parts.rank':'parts:measured records, host,condition,role,metric,unit,target. Excludes incomparable/missing-source measurements; promoter/RBS/terminator choice.',
 'circuit.simulate':'genes:[{name,transcription,translation,mrna_decay,protein_decay,regulators:[{gene,mode:activate|repress,K,n}],initial_mrna,initial_protein}],duration,points,dilution,rtol,atol. Consistent user units.',
 'bioprocess.simulate':'mu_max,Ks,yield_xs,biomass_g_l,substrate_g_l,product_g_l,volume_l,duration_h; optional alpha,beta,feed_l_h,feed_substrate_g_l,death_h,rtol,atol. Monod model.',
 'ncbi.search':'db:nuccore|protein|gene|assembly|pubmed, query, limit:1..20. Internet required; actual ESearch IDs.',
 'ncbi.fetch':'db:nuccore|protein, id:accession.version or UID, optional start/end:1-based inclusive (nuccore only). Bounded GenBank/GenPept retrieval.',
 'igem.part':'id:BBa_...; current public iGEM Registry record and sequence with source/license metadata. Internet required.',
 'genome.browser':'accession:NC_...version, optional start/end:1-based inclusive. NCBI viewer link; no local sequence upload.',
 'biology.help':'Operation schemas. Add export:true to save JSON for analysis operations.'
}


from Scientific.science_extensions import HELP as EXTENSION_HELP
HELP.update(EXTENSION_HELP)

class Context:
    def __init__(self,root):
        from profile_paths import capture
        self.root=Path(root).resolve();self.identity=capture(self.root)
        self.started=time.time();self.deadline=time.monotonic()+120
    def check(self):
        from profile_paths import capture, ProfileLocked, _contained
        if capture(self.root)!=self.identity:raise ProfileLocked('The biology request login ended')
        if time.monotonic()>self.deadline:raise TimeoutError('Biology request exceeded its wall-clock budget')
        for name in ('qwen_last_stop.json','native_startup_state.json'):
            path=_contained(self.root,self.root/'Agent/.runtime'/name)
            if path.exists():
                if path.stat().st_size>16384:raise RuntimeError('Invalid Stop marker')
                if json.loads(path.read_text(encoding='utf-8')).get('stopped_at',0)>=self.started:
                    raise RuntimeError('Biology request cancelled by Stop')


def publish(context,p,contents):
    from profile_paths import private_path,_contained
    from media_paths import media_output
    from runtime_policy import require_space
    context.check();root=context.root
    if any(not re.fullmatch(r'[a-zA-Z0-9_.-]+',name) or name in ('.','..') for name in contents):raise ValueError('Invalid output filename')
    contents={name:(value if isinstance(value,bytes) else value.encode('utf-8')) for name,value in contents.items()}
    total=sum(len(s) for s in contents.values())
    if total>16*1024**2:raise ValueError('Biology output exceeds 16 MiB')
    require_space(root,total,for_outputs=True)
    parent=media_output(root,p['output_dir']) if p.get('output_dir') else private_path(root,'Outputs/Science/Biology',context=context.identity)
    _contained(root,parent);context.check();parent.mkdir(parents=True,exist_ok=True)
    target=parent/('biology_'+uuid.uuid4().hex);staging=parent/(target.name+'.partial')
    staging.mkdir();folder=staging;owned={}
    try:
        for name,text in contents.items():
            context.check();path=_contained(root,staging/name)
            with path.open('xb') as out:
                stat=os.fstat(out.fileno());owned[name]=(stat.st_dev,stat.st_ino)
                out.write(text);out.flush();os.fsync(out.fileno())
            context.check()
        context.check();_contained(root,staging);_contained(root,target)
        from profile_lazy_state import publish_no_replace
        publish_no_replace(staging,target);folder=target;context.check()
    except BaseException:
        for name,identity in owned.items():
            path=_contained(root,folder/name)
            if path.exists():
                stat=path.lstat()
                if (stat.st_dev,stat.st_ino)!=identity:raise RuntimeError('Biology cleanup refused a replaced output')
                path.unlink()
        if folder.exists():folder.rmdir()
        raise
    return [str(target/name) for name in contents]


def public_request(context,url):
    from web_tools import _request_bytes
    from web_state import WebState
    from mission_runner import process_lock
    from profile_paths import private_path,_contained
    state=WebState(context.root);context.check()
    provider='biology:'+urlparse(url).hostname
    cached=state.cached(url,1)
    if cached:
        return cached['results'][0]['text'],cached['results'][0]['source'],True
    cooldown=state.cooling(provider)
    if cooldown:raise RuntimeError('Database cooldown: '+str(cooldown))
    lock=private_path(context.root,'Cache/Web/biology-network.lock',context=context.identity)
    _contained(context.root,lock)
    # Serialize this profile's processes and stay below NCBI's no-key 3/s rate.
    with process_lock(lock):
        context.check();time.sleep(.4);context.check()
        try:data,final,kind=_request_bytes(url,timeout=15,max_bytes=4*1024**2)
        except Exception:
            context.check();state.block(provider,30,'Database request failed; retry later');raise
        context.check()
        if urlparse(final).scheme!='https':raise ValueError('Database HTTPS downgrade refused')
        if 'text/html' in kind:raise ValueError('Database returned an HTML page, not a record')
        text=data.decode('utf-8')
        state.save(url,1,{'provider':provider,'results':[{'text':text,'source':final}]})
        context.check();return text,final,False


def network(operation,p,context):
    if operation=='igem.part':
        name=p['id']
        if not isinstance(name,str) or not re.fullmatch(r'BBa_[A-Za-z0-9]{4,20}',name):raise ValueError('Invalid iGEM part identifier')
        text,source,cached=public_request(context,'https://api.registry.igem.org/v1/parts?'+urlencode({'name':name}))
        rows=[x for x in json.loads(text).get('data',[]) if x.get('name')==name]
        if len(rows)!=1:raise ValueError('Registry did not return one exact identifier match')
        identifier=str(uuid.UUID(rows[0]['uuid']))
        text,source,cached=public_request(context,'https://api.registry.igem.org/v1/parts/'+identifier)
        record=json.loads(text)
        if record.get('name')!=name or record.get('uuid')!=identifier:raise ValueError('Registry record identity mismatch')
        if record.get('sequence'):biology.sequence(record['sequence'])
        return {'record':record,'source_url':source,'cached':cached,'accessed_at':time.time(),'sequence_available':bool(record.get('sequence')),
                'limitations':['Registry annotations are source data, not verified expression strength. Preserve license and chassis metadata.']}
    db=p.get('db','nuccore')
    if db not in ('nuccore','protein','gene','assembly','pubmed'):raise ValueError('Unsupported NCBI database')
    if operation=='ncbi.search':
        query=p['query']
        if not isinstance(query,str) or not 1<=len(query)<=500:raise ValueError('Query must contain 1..500 characters')
        query_args={'db':db,'term':query,'retmode':'json','retmax':biology.integer(p.get('limit',10),'limit',1,20),'tool':'PortalAI'}
        endpoint='esearch.fcgi'
    else:
        if db not in ('nuccore','protein'):raise ValueError('Fetch supports nuccore or protein')
        identifier=str(p['id'])
        if not re.fullmatch(r'[A-Za-z0-9_.]{1,40}',identifier):raise ValueError('Provide one accession/version or numeric UID')
        query_args={'db':db,'id':identifier,'rettype':'gb' if db=='nuccore' else 'gp','retmode':'text','tool':'PortalAI'}
        if 'start' in p or 'end' in p:
            if db!='nuccore':raise ValueError('Coordinate subsets currently support nuccore only')
            start=biology.integer(p['start'],'start',1,10**10);end=biology.integer(p['end'],'end',start,start+200000-1)
            query_args.update(seq_start=start,seq_stop=end)
        endpoint='efetch.fcgi'
    text,source,cached=public_request(context,'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'+endpoint+'?'+urlencode(query_args))
    if operation=='ncbi.search':
        data=json.loads(text)
        if 'error' in data or 'esearchresult' not in data or data['esearchresult'].get('ERROR'):raise ValueError('NCBI search failed: '+str(data)[:300])
        return {'database':db,'result':data['esearchresult'],'source_url':source,'cached':cached}
    if not text.lstrip().startswith('LOCUS') or not text.rstrip().endswith('//'):raise ValueError('NCBI did not return a complete GenBank/GenPept record')
    from Bio import SeqIO
    import io
    record=SeqIO.read(io.StringIO(text),'genbank')
    return {'database':db,'id':record.id,'length':len(record),'text':text,'source_url':source,'cached':cached,
            'sha256':hashlib.sha256(text.encode()).hexdigest()}


def run(operation,p,root):
    if not isinstance(p,dict) or len(json.dumps(p,allow_nan=False).encode())>5*1024**2:raise ValueError('Expected a bounded JSON object')
    context=Context(root);context.check()
    if operation=='genome.specificity':context.deadline=time.monotonic()+600
    if operation=='biology.help':return {'operations':HELP,'compute':'cpu','files':[]}
    from runtime_policy import memory_info
    if memory_info()[1]<768*1024**2:raise RuntimeError('Biology tools require at least 768 MiB free RAM')
    p=dict(p);contents={}
    if operation=='genome.features' and p.get('file'):
        from media_paths import media_reference
        context.check();path=media_reference(context.root,p['file'])
        with path.open('rb') as f:data=f.read(4*1024**2+1)
        if len(data)>4*1024**2:raise ValueError('GenBank file exceeds 4 MiB; select a region')
        context.check();p['text']=data.decode('utf-8')
    if operation in EXTENSION_HELP:
        from Scientific.science_extensions import run as extension_run
        result,contents=extension_run(operation,p,context)
    elif operation in biology.OPERATIONS:
        result=biology.OPERATIONS[operation](p,context.check)
        if isinstance(result,tuple):result,contents=result
    elif operation in ('ncbi.search','ncbi.fetch','igem.part'):result=network(operation,p,context)
    elif operation=='genome.browser':
        accession=p['accession']
        if not isinstance(accession,str) or not re.fullmatch('[A-Za-z0-9_.]{1,40}',accession):raise ValueError('Invalid accession')
        parameters={'report':'graph'}
        if 'start' in p or 'end' in p:
            start=biology.integer(p['start'],'start',1,10**10);end=biology.integer(p['end'],'end',start,10**10)
            parameters.update({'from':start,'to':end})
        result={'url':'https://www.ncbi.nlm.nih.gov/nuccore/'+accession+'?'+urlencode(parameters),
                'coordinates':'1-based inclusive','uploaded_local_data':False,'requires_internet':True}
    elif operation in ('protein.inspect','protein.structure_variants'):
        from Scientific.protein_structure import run as structure_run
        result,contents=structure_run(operation,p,context)
    elif operation=='protein.design':
        from Scientific.protein_design import design
        result=design(p,context)
    else:raise ValueError('Unknown biology operation')
    context.check();export=p.get('export',bool(contents))
    if not isinstance(export,bool):raise ValueError('export must be boolean')
    if export:
        contents['result.json']=json.dumps(result,ensure_ascii=True,indent=2,allow_nan=False)
        files=publish(context,p,contents)
    else:files=[]
    context.check()
    return {**result,'compute':result.get('compute','cpu'),'files':files,'biology_version':'2026-10-10'}
