"""Read-only progress for the portable installed-GGUF campaign."""
import json, shutil, sqlite3, time
from pathlib import Path
LAB=Path(__file__).resolve().parent

def status():
    result={'time_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
            'gpu_paused':(LAB/'GPU-PAUSED.json').exists(),
            'free_gib':round(shutil.disk_usage(LAB).free/1024**3,2),'models':{}}
    protocol=json.loads((LAB/'protocol.json').read_text())
    for name in protocol['models']:
        folder=LAB/'experiments'/name;row={'phase':'not started'}
        ledger=folder/'ledger.sqlite'
        if ledger.is_file():
            with sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True) as db:
                runs=db.execute('SELECT id,phase,status FROM runs ORDER BY created,id').fetchall()
            running=[r[0] for r in runs if r[2]=='running']
            row={'phase':running[-1] if running else 'between passes',
                 'completed_passes':sum(r[2]=='complete' for r in runs),
                 'interrupted_passes':sum(r[2]=='interrupted' for r in runs)}
            if row['phase'].startswith('001'):
                cases=folder/row['phase']
                row['completed_cases']=sum(p.name!='request.json' for p in cases.glob('*.json'))
        summary=folder/'004-generation-screen/summary.json'
        if summary.is_file():
            data=json.loads(summary.read_text());paired=data['paired'];control=data['random_control']
            row.update(phase='discovery complete',cases=paired['n'],original=paired['baseline_correct'],
                       edited=paired['candidate_correct'],random=control['candidate_correct'],
                       eligible_for_confirmation=data['eligible_for_independent_confirmation'])
        result['models'][name]=row
    return result

if __name__=='__main__':print(json.dumps(status(),indent=2))
