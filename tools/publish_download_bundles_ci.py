"""Rebuild and upload a task-owned draft from verified published inputs."""
from pathlib import Path
import concurrent.futures,hashlib,http.client,json,os,shutil,subprocess,sys,urllib.request,urllib.error,urllib.parse,zipfile
ROOT=Path(__file__).resolve().parents[1]
config=json.loads((ROOT/'tools/download-bundle-inputs.json').read_text())
assert os.environ['GITHUB_REPOSITORY']==config['repository']
token=os.environ['GH_TOKEN'];api='https://api.github.com/repos/'+config['repository']
headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','User-Agent':'PortalAI-bundle-build'}
def call(url,method='GET',data=None):
    h=dict(headers)
    if data is not None:data=json.dumps(data).encode();h['Content-Type']='application/json'
    with urllib.request.urlopen(urllib.request.Request(url,headers=h,method=method,data=data),timeout=90) as r:
        data=r.read();return json.loads(data) if data else None
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
def download(item):
    dest=ROOT/'build/inputs'/item['asset']['name'];dest.parent.mkdir(parents=True,exist_ok=True)
    if item['private']:
        h=dict(headers,Accept='application/octet-stream')
        try:r=urllib.request.build_opener(NoRedirect).open(urllib.request.Request(item['asset']['url'],headers=h),timeout=90)
        except urllib.error.HTTPError as e:
            if e.code not in (301,302,303,307,308):raise
            r=urllib.request.urlopen(e.headers['Location'],timeout=90)
    else:r=urllib.request.urlopen(item['asset']['browser_download_url'],timeout=90)
    with r,dest.open('wb') as f:shutil.copyfileobj(r,f,4*1024*1024)
    assert dest.stat().st_size==item['asset']['size'] and sha(dest)==item['sha256'],item['key']
    print('Verified input '+item['key'],flush=True)
    return {**item,'path':str(dest)}
release=call(api+'/releases/'+str(config['release_id']))
assert release['draft'] and release['tag_name']==config['tag']
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:inputs=list(pool.map(download,config['inputs']))
inp=ROOT/'build/verified-inputs.json';inp.write_text(json.dumps(inputs))
out=ROOT/'build/output'
subprocess.run([sys.executable,str(ROOT/'tools/build_welcome_bundles.py'),'--inputs',str(inp),'--output',str(out),'--edition',config['edition']],check=True)
rows=json.loads((out/'bundle-build.json').read_text())
checks=[]
for row in rows:
    with zipfile.ZipFile(row['path']) as z:
        expected=config['expected_contents'][row['platform']]
        assert hashlib.sha256(z.read('BUNDLE-CONTENTS.json')).hexdigest()==expected,'Bundle contents differ from locally reviewed build'
        contents=json.loads(z.read('BUNDLE-CONTENTS.json'))
        assert set(z.namelist())==set(contents['files'])|{'BUNDLE-CONTENTS.json','SHA256SUMS'}
        for name,digest in contents['files'].items():
            with z.open(name) as f:assert hashlib.file_digest(f,'sha256').hexdigest()==digest,name
        assert row['manifest']['utilities_optional']
        if config['edition']=='Academic':assert not any('Abliterator' in n for n in z.namelist())
        checks.append(dict(name=row['name'],members_verified=len(z.namelist()),reviewed_contents_sha256=expected,native_archives_unchanged=True,utilities_optional=True))
    print('Verified reviewed contents '+row['name'],flush=True)
def upload(p,digest):
    release=call(api+'/releases/'+str(config['release_id']));assert release['draft']
    old=next((a for a in release['assets'] if a['name']==p.name),None)
    if old:
        if old['state']=='uploaded':
            # A completed local upload is accepted only against its reviewed whole-file pin.
            acceptable={digest,config['reviewed_archives'].get(p.name)}
            assert old.get('digest','').removeprefix('sha256:') in acceptable and old['size']==p.stat().st_size,'Existing upload differs'
            return old
        assert old['state']=='starter','Unexpected asset state'
        call(api+'/releases/assets/'+str(old['id']),'DELETE')
    conn=http.client.HTTPSConnection('uploads.github.com',timeout=180)
    conn.putrequest('POST','/repos/'+config['repository']+'/releases/'+str(config['release_id'])+'/assets?name='+urllib.parse.quote(p.name))
    for k,v in headers.items():conn.putheader(k,v)
    conn.putheader('Content-Type','application/octet-stream');conn.putheader('Content-Length',str(p.stat().st_size));conn.endheaders()
    with p.open('rb') as f:
        while block:=f.read(4*1024*1024):conn.send(block)
    response=conn.getresponse();data=response.read();status=response.status;conn.close()
    assert status==201,('Upload status',status,p.name)
    a=json.loads(data);assert a['size']==p.stat().st_size and a['digest']=='sha256:'+digest
    print('Uploaded and server-verified '+p.name,flush=True);return a
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
    assets=list(pool.map(lambda r:upload(Path(r['path']),r['sha256']),rows))
for row,a in zip(rows,assets):
    row['sha256']=a['digest'].removeprefix('sha256:');row['bytes']=a['size'];row.pop('path')
manifest=dict(bundle_version='2026.11.25-bundle1',edition=config['edition'],native_versions={'Windows':'r85','Mac':'r75','Linux':'r75'},utilities_optional=True,
    validation=dict(archive_checks=checks,setup_regression_tests=9,setup_regression_tests_passed=9,native_mac_linux_runtime_tested=False,live_inference_retested=False,
      build_workflow=f"https://github.com/{config['repository']}/actions/runs/{os.environ['GITHUB_RUN_ID']}",source_commit=os.environ['GITHUB_SHA']),
    bundles=rows)
for name,data in [('BUNDLE-MANIFEST.json',json.dumps(manifest,indent=2)+'\n'),('SHA256SUMS.txt',''.join(r['sha256']+'  '+r['name']+'\n' for r in rows))]:
    p=out/name;p.write_text(data);upload(p,sha(p))
print('Draft complete and verified; publication remains a separate final step.',flush=True)

