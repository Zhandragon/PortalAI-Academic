"""Portable pLannotate DNA/protein annotation; no remote sequence submission."""
import hashlib, io, json, os, re
from pathlib import Path
from Scientific.extensions_common import keys, read, worker

LIMITATIONS = [
    'Rfam/Infernal RNA covariance searches are not included in this Windows package.',
    'Sequence similarity is annotation evidence, not proof of expression, activity, safety or phenotype. Missing hits are not biological absence.',
    'Intended for engineered DNA/plasmids, not whole-genome gene prediction. Fast mode omits Swiss-Prot protein coverage.'
]

def inventory(root, verify=False, check=lambda: None):
    from profile_paths import _contained
    receipt = _contained(root, root/'Maintenance/Imports/plannotate.json')
    if receipt.stat().st_size > 256*1024: raise ValueError('Oversized pLannotate receipt')
    data = json.loads(receipt.read_text())
    rows = data['files']
    if not isinstance(rows,list) or not 1 <= len(rows) <= 500: raise ValueError('Invalid pLannotate inventory')
    seen = set()
    for row in rows:
        rel = row['path']
        if not isinstance(rel,str) or not rel.startswith('Tools/pLannotate/') or '\\' in rel or '..' in Path(rel).parts or rel in seen:
            raise ValueError('Invalid pLannotate asset path')
        seen.add(rel)
        if not re.fullmatch('[0-9a-f]{64}',row['sha256']) or type(row['bytes']) is not int or row['bytes']<0:
            raise ValueError('Invalid pLannotate asset pin')
        p = _contained(root,root/rel); check()
        if not p.is_file() or p.stat().st_size != row['bytes']: raise RuntimeError('Missing or damaged pLannotate asset: '+rel)
        if verify:
            with p.open('rb') as f:
                h=hashlib.sha256()
                while chunk:=f.read(1024**2):h.update(chunk);check()
            if h.hexdigest()!=row['sha256']: raise RuntimeError('pLannotate checksum mismatch: '+rel)
    required={'Tools/pLannotate/bin/blastn.exe','Tools/pLannotate/bin/diamond.exe',
              'Tools/pLannotate/vendor/plannotate/annotate.py','Tools/pLannotate/databases/BLAST_dbs/snapgene.nsq',
              'Tools/pLannotate/databases/diamond_dbs/fpbase.dmnd','Tools/pLannotate/databases/diamond_dbs/swissprot.dmnd'}
    if not required<=seen: raise ValueError('Incomplete pLannotate receipt')
    return data

def run(p, context):
    keys(p,{'sequence','file','circular','name','mode','engine'})
    if p.get('engine','plannotate')!='plannotate': raise ValueError('This route requires engine:plannotate')
    if os.name!='nt': raise RuntimeError('This pLannotate package currently supports Windows x64 only')
    if ('sequence' in p)==('file' in p): raise ValueError('Supply sequence or a single-record FASTA/GenBank file')
    topology=None
    if 'file' in p:
        from Bio import SeqIO
        text=read(context,p['file'],4*1024**2).decode('utf-8-sig')
        record=SeqIO.read(io.StringIO(text),'genbank' if text.lstrip().startswith('LOCUS') else 'fasta')
        sequence=str(record.seq);topology=record.annotations.get('topology')
    else: sequence=p['sequence']
    if not isinstance(sequence,str): raise ValueError('DNA sequence must be text')
    sequence=''.join(sequence.split()).upper()
    if not 20<=len(sequence)<=100000 or set(sequence)-set('ACGTN'): raise ValueError('pLannotate requires 20..100000 A/C/G/T/N bases')
    circular=p.get('circular',topology!='linear')
    if not isinstance(circular,bool): raise ValueError('circular must be boolean')
    mode=p.get('mode','standard')
    if mode not in ('standard','fast'): raise ValueError('mode must be standard or fast')
    name=p.get('name','annotated')
    if not isinstance(name,str) or not 1<=len(name)<=120: raise ValueError('name requires 1..120 characters')
    receipt=inventory(context.root,True,context.check)
    result,files=worker(context,'plannotate',{'sequence':sequence,'circular':circular,'name':name,'mode':mode},timeout=100)
    result.update(engine='pLannotate',version=receipt['version'],source_revision=receipt['revision'],
                  database_version=receipt['database_version'],limitations=LIMITATIONS,
                  uploaded_sequence=False)
    return result,files

def feature_svg(sequence_length, rows):
    """Static, escaped map; full alignment evidence remains in GenBank/CSV."""
    from html import escape
    visible=rows[:100];height=80+24*len(visible)
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="{height}" viewBox="0 0 1100 {height}">',
           '<rect width="100%" height="100%" fill="#faf7ed"/>',
           '<text x="20" y="25" font-family="sans-serif" font-size="16">pLannotate DNA/protein features (RNA family search excluded)</text>',
           f'<text x="20" y="48" font-family="sans-serif" font-size="12">{sequence_length} bp; forward coordinates; first {len(visible)} of {len(rows)} features. Full evidence: annotated.gb and features.csv.</text>']
    for i,row in enumerate(visible):
        y=68+24*i;start=int(row['qstart']);end=int(row['qend']);label=escape(str(row['name'])[:44])
        parts.append(f'<text x="20" y="{y+12}" font-family="sans-serif" font-size="12">{label}</text>')
        spans=[(start,min(end,sequence_length))]
        if end>sequence_length:spans.append((0,end-sequence_length))
        for a,b in spans:
            x=350+700*a/sequence_length;width=max(1,700*(b-a)/sequence_length)
            parts.append(f'<rect x="{x:.2f}" y="{y}" width="{width:.2f}" height="14" fill="#{"318aa0" if row["sframe"]==1 else "a57b34"}"/>')
    return ''.join(parts)+'</svg>'

def execute_worker(p,folder,root):
    """Runs only within the existing owned/gated science job."""
    import sys,tempfile
    sys.path[:0]=[str(root/'Tools/pLannotate/vendor'),str(root/'Runtime/ScientificPython/packages'),str(root/'Runtime/SciencePackages')]
    # Upstream temporary FASTA/results remain inside this profile-bound worker folder.
    tempfile.tempdir=str(folder)
    os.environ['TMP']=os.environ['TEMP']=str(folder)
    os.environ['PATH']=str(root/'Tools/pLannotate/bin')+os.pathsep+os.environ.get('PATH','')
    os.environ['BLAST_USAGE_REPORT']='false'
    import yaml
    from plannotate import Construct
    from plannotate._tools import blast,diamond
    import subprocess
    def command(argv,tool):
        name=Path(argv[0]).name.removesuffix('.exe')
        if name not in ('blastn','diamond'): raise ValueError('Unexpected annotation executable')
        result=subprocess.run([str(root/'Tools/pLannotate/bin'/(name+'.exe')),*argv[1:]],
            capture_output=True,text=True,timeout=95,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode: raise RuntimeError(name+' failed: '+(result.stderr or result.stdout)[-1500:])
    blast.run_command=diamond.run_command=command
    config=yaml.safe_load((root/'Tools/pLannotate/vendor/plannotate/data/data/databases.yml').read_text())
    names=['snapgene','fpbase']+(['swissprot'] if p['mode']=='standard' else [])
    config={name:config[name] for name in names}
    for name,value in config.items():
        location=root/'Tools/pLannotate/databases'/('BLAST_dbs' if name=='snapgene' else 'diamond_dbs')
        value['location']=str(location)
        value['details']['location']=str(location/(name+'.db'))
        if name!='snapgene':value['parameters'].extend(['--block-size 0.1','--file-buffer-size 1048576'])
    config_path=folder/'annotation-config.json'
    with config_path.open('x',encoding='utf-8') as f:
        identity=os.fstat(f.fileno());f.write(json.dumps(config));f.flush();os.fsync(f.fileno())
    try:
        # Always double circular input. Mode selects sources only, retaining full seam handling.
        construct=Construct(p['sequence'],linear=not p['circular'],db_options=config_path,name=p['name'],cores=1,fast=False)
        frame=construct.annotations_df
        if len(frame)>10000: raise ValueError('More than 10000 annotations; reduce input size')
        rows=json.loads(frame.to_json(orient='records'))
        (folder/'annotated.gb').write_text(construct.to_genbank(),encoding='utf-8')
        (folder/'features.csv').write_text(construct.to_csv().to_csv(index=False),encoding='utf-8')
        (folder/'feature-map.svg').write_text(feature_svg(len(p['sequence']),rows),encoding='utf-8')
        return {'length':len(p['sequence']),'circular':p['circular'],'mode':p['mode'],'databases':names,
                'feature_count':len(rows),'features':rows,'coordinates':'0-based half-open forward sequence; circular end may exceed length'}
    finally:
        current=config_path.lstat()
        if (current.st_dev,current.st_ino)!=(identity.st_dev,identity.st_ino):raise RuntimeError('Annotation config identity changed')
        config_path.unlink()
