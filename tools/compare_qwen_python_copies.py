from pathlib import Path
import hashlib,json,os,sys,time
def files(root):
 result={}
 for base,dirs,names in os.walk(root):
  dirs[:]=[n for n in dirs if n!='__pycache__']
  for name in names:
   if name.endswith(('.pyc','.pyo')):continue
   p=Path(base)/name;result[p.relative_to(root).as_posix()]=p
 return result
def digest(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
for drive in sys.argv[1:]:
 assert drive in ('D','E');root=Path(drive+':/PortalAI Windows');base=root/'Voice/Qwen3-TTS'
 a=files(base/'.venv/Lib/site-packages');b=files(base/'python/cpython-3.12.14-windows-x86_64-none/Lib/site-packages');same=[];different=[];total=0;linked=0
 for name in sorted(a.keys()&b.keys()):
  x=a[name].stat();y=b[name].stat()
  if x.st_size==y.st_size and digest(a[name])==digest(b[name]):
   same.append(name);total+=x.st_size
   if x.st_ino==y.st_ino:linked+=x.st_size
  else:different.append(name)
 report={'read_only':True,'equal_files':len(same),'equal_bytes':total,'already_hardlinked_bytes':linked,'different':different,'only_venv':sorted(a.keys()-b.keys()),'only_base':sorted(b.keys()-a.keys()),'runtime_changes':False}
 (root/'Maintenance/Validation/Integration-20261029/qwen-duplicate-comparison.json').write_text(json.dumps(report,indent=2))
 print(drive,json.dumps({k:v for k,v in report.items() if k not in ('different','only_venv','only_base')}),'different',len(different),'unique',len(report['only_venv']),len(report['only_base']),flush=True)
