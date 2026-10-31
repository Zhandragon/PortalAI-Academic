"""Run the shipped NativeChat handoff test with normal effort preparation."""
import json,os,sys
from pathlib import Path
ROOT=Path(__file__).with_name('listener-fixture').resolve()
assert json.loads((ROOT/'fixture-manifest.json').read_text())['no_owner_accounts']
assert Path(sys.executable).resolve()==ROOT/'Runtime/BootstrapPython/python.exe'
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Tools')]
for key in ('PYTHONHOME','PYTHONPATH','PORTALAI_PROFILE_ID','PORTALAI_PROFILE_EPOCH','PORTALAI_ACCOUNT_UNLOCK'):os.environ.pop(key,None)
os.environ.update(PORTABLEAI_ROOT=str(ROOT),HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONDONTWRITEBYTECODE='1',TEMP=str(ROOT/'Cache/tmp'),TMP=str(ROOT/'Cache/tmp'))
from instance_runtime import InstanceSession
session=InstanceSession(ROOT);session.start()
import service_manager as service
from chat_model_switch import prepare_startup
import smoke_chat_handoff
try:
    prepare_startup(ROOT,on_status=lambda msg:print(msg,flush=True))
    sys.argv=[str(ROOT/'Tools/smoke_chat_handoff.py'),'--case','error','--effort',os.environ.get('PORTALAI_VALIDATION_EFFORT','fast'),'--report','listener-prepared-handoff.json']
    code=smoke_chat_handoff.main()
finally:
    service._stop_qwen_listener();session.close()
raise SystemExit(code)
