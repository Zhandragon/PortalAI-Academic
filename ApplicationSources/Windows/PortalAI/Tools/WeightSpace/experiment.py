"""Durable experiment accounting and paired evidence; no automatic promotion."""
import contextlib,hashlib,json,math,os,shutil,sqlite3,time
from pathlib import Path
FLOOR=80*1024**3

def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def atomic_json(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.writing')
    with temporary.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(temporary,path)

def space(path,additional=0):
    free=shutil.disk_usage(path).free
    if free-additional<FLOOR:raise RuntimeError('This operation would leave less than 80 GiB free on the portable drive.')
    return free

class Ledger:
    def __init__(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path,timeout=10)
        self.db.execute('PRAGMA journal_mode=DELETE');self.db.execute('PRAGMA synchronous=FULL')
        self.db.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, phase TEXT NOT NULL, request TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, evidence TEXT)')
        self.db.commit()

    def begin(self,identifier,phase,request):
        if phase not in ('discovery','confirmation','final','cpu'):raise ValueError('Invalid experiment phase')
        digest=hashlib.sha256(json.dumps(request,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old=self.db.execute('SELECT request,status FROM runs WHERE id=?',(identifier,)).fetchone()
            if old:
                if old[0]!=digest:raise RuntimeError('A saved pass has different settings; use a new pass ID.')
                if old[1]=='complete':return False
                raise RuntimeError('An interrupted pass needs explicit reconciliation before retrying.')
            if phase in ('discovery','confirmation'):
                count=self.db.execute("SELECT COUNT(*) FROM runs WHERE phase IN ('discovery','confirmation') AND status IN ('running','complete','interrupted')").fetchone()[0]
            else:
                count=self.db.execute("SELECT COUNT(*) FROM runs WHERE phase=? AND status IN ('running','complete','interrupted')",(phase,)).fetchone()[0]
            if phase in ('discovery','confirmation','cpu') and count>=(300 if phase=='cpu' else 50):raise RuntimeError('Scientific tool budget exhausted')
            self.db.execute('INSERT INTO runs VALUES(?,?,?,?,?,NULL)',(identifier,phase,digest,'running',time.time()))
        return True

    def end(self,identifier,evidence,success=True):
        with self.db:
            changed=self.db.execute("UPDATE runs SET status=?, evidence=? WHERE id=? AND status='running'",('complete' if success else 'interrupted',json.dumps(evidence,sort_keys=True),identifier)).rowcount
            if changed!=1:raise RuntimeError('Pass is not running')

    def close(self):self.db.close()

def paired_summary(baseline,candidate):
    """Case-keyed paired normal interval, with rescues/regressions reported."""
    if not baseline or set(baseline)!=set(candidate):raise ValueError('Comparisons require exactly matching case IDs')
    if any(type(v) is not bool for v in list(baseline.values())+list(candidate.values())):raise ValueError('Scores must be booleans')
    n=len(baseline);d=[int(candidate[k])-int(baseline[k]) for k in baseline];mean=sum(d)/n
    se=math.sqrt(sum((x-mean)**2 for x in d)/(n*(n-1))) if n>1 else float('inf')
    return {'n':n,'baseline_correct':sum(baseline.values()),'candidate_correct':sum(candidate.values()),'gain':mean,
            'rescues':d.count(1),'regressions':d.count(-1),'paired_standard_error':se,
            'lower_95':mean-1.96*se,'upper_95':mean+1.96*se}

def promotion_gate(confirmation,domains,*,latency_ratio,required=('math','coding','tools','instruction'),minimum_n=1152):
    reasons=[]
    if confirmation['n']<minimum_n or confirmation['lower_95']<=0:reasons.append('Independent paired confirmation has not established an accuracy gain.')
    if not set(required)<=set(domains):reasons.append('Required broad benchmark domains are missing.')
    if any(row['gain']<-.02 for row in domains.values()):reasons.append('A broad domain regressed by more than two percentage points.')
    if not domains or sum(row['gain'] for row in domains.values())<=0:reasons.append('No aggregate broad benchmark gain.')
    if not math.isfinite(latency_ratio) or latency_ratio>1.15:reasons.append('Processing time increased by more than 15%.')
    return {'eligible':not reasons,'reasons':reasons,'production_model_changed':False}
