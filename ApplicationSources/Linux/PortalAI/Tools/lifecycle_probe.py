from __future__ import annotations
import csv, http.client, json, os, socket, subprocess, time
from pathlib import Path

VERSION="15.134c"; HOST="127.0.0.1"; QWEN_PORT=8080
CREATE_NO_WINDOW=getattr(subprocess,"CREATE_NO_WINDOW",0x08000000 if os.name=="nt" else 0)

def port_open(port:int,timeout:.2=.2)->bool:
    try:
        with socket.create_connection((HOST,int(port)),timeout=timeout):return True
    except OSError:return False

def _http(path:str,timeout=.7):
    c=http.client.HTTPConnection(HOST,QWEN_PORT,timeout=timeout)
    try:
        c.request("GET",path,headers={"Connection":"close","Accept":"application/json"});r=c.getresponse();raw=r.read(512000).decode("utf-8",errors="replace")
        try:d=json.loads(raw) if raw else None
        except Exception:d=None
        return r.status,d,raw
    except Exception as e:return None,None,str(e)
    finally:
        try:c.close()
        except Exception:pass

def _run(args,timeout=20):return subprocess.run(args,capture_output=True,text=True,errors="replace",timeout=timeout,creationflags=(CREATE_NO_WINDOW if os.name=="nt" else 0))

def port_pids_windows(port:int)->list[int]:
    if os.name!="nt":
        import sys
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Agent'))
        from linux_process import listeners
        return listeners(port)
    try:
        cp=_run(["netstat","-ano","-p","tcp"]);out=set()
        for l in (cp.stdout or "").splitlines():
            p=l.split()
            if len(p)>=5 and p[0].upper()=="TCP" and p[3].upper()=="LISTENING" and p[1].rsplit(":",1)[-1]==str(port):
                try:out.add(int(p[4]))
                except Exception:pass
        return sorted(out)
    except Exception:return []

def _proc(pid:int)->dict:
    if os.name!="nt":
        from linux_process import identity
        try:
            import shlex
            row=identity(pid);return {'pid':pid,'name':Path(row['executable']).name,'image':row['executable'],'command_line':shlex.join(row['argv'])}
        except OSError:return {'pid':pid}
    ps=f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId={int(pid)}\";if($p){{$p|Select-Object ProcessId,Name,ExecutablePath,CommandLine|ConvertTo-Json -Compress}}"
    try:
        cp=_run(["powershell.exe","-NoProfile","-Command",ps]);d=json.loads((cp.stdout or "{}").strip() or "{}")
        return {"pid":pid,"name":d.get("Name"),"image":d.get("ExecutablePath"),"command_line":d.get("CommandLine")}
    except Exception:return {"pid":pid}

def probe_qwen(root:Path)->dict:
    root=Path(root).resolve(); online=port_open(QWEN_PORT); listeners=[_proc(p) for p in port_pids_windows(QWEN_PORT)]
    if not online:return {"online":False,"active":False,"ready":False,"sleeping":False,"state":"stopped","port":QWEN_PORT,"listeners":[]}
    hs,health,hr=_http("/health");ps,props,pr=_http("/props");ms,models,mr=_http("/v1/models")
    lowroot=os.path.normcase(str(root)).lower()
    process_identity=any("llama-server" in str(x.get("name") or "").lower() and (not x.get("command_line") or lowroot in os.path.normcase(str(x.get("command_line"))).lower()) for x in listeners)
    props_identity=isinstance(props,dict) and any(k in props for k in ("model_path","is_sleeping","build_info"))
    model_items=models.get("data") if isinstance(models,dict) else None;model_identity=isinstance(model_items,list)
    is_llama=bool(process_identity or props_identity or model_identity)
    if not is_llama:return {"online":True,"active":False,"ready":False,"sleeping":False,"state":"conflict","port":QWEN_PORT,"listeners":listeners,"detail":"port 8080 occupied by unrecognized service"}
    sleeping=bool(props.get("is_sleeping")) if isinstance(props,dict) else False
    model_path=str(props.get("model_path") or "") if isinstance(props,dict) else ""; model=Path(model_path).name if model_path else None
    if sleeping:state,ready,detail="sleeping",False,"llama-server active; model sleeping"
    elif hs==200:state,ready,detail="ready",True,"llama-server ready"
    elif hs==503:state,ready,detail="loading",False,"llama-server loading"
    else:state,ready,detail="active",False,"llama-server listener identified"
    return {"online":True,"active":True,"ready":ready,"sleeping":sleeping,"state":state,"port":QWEN_PORT,"listeners":listeners,"model":model,"model_path":model_path or None,"detail":detail,"health_status":hs,"props_status":ps,"models_status":ms}

def handoff_state(root:Path)->dict:
    rt=Path(root)/"Agent"/".runtime";gen=rt/"qwen_handoff_generation.json";states=[]
    current=None
    if gen.exists():
        try:current=json.loads(gen.read_text(encoding="utf-8",errors="replace"))
        except Exception:current={"error":"unreadable generation state"}
    for p in sorted(rt.glob("qwen_handoff_*.json")):
        try:d=json.loads(p.read_text(encoding="utf-8",errors="replace"));d["file"]=p.name;states.append(d)
        except Exception:states.append({"file":p.name,"error":"unreadable"})
    return {"current_generation":current,"handoffs":states}
