from __future__ import annotations
import sys as _instance_sys
from pathlib import Path as _InstancePath
_instance_sys.path.insert(0, str(_InstancePath(__file__).resolve().parents[1]/'Agent'))
from instance_runtime import port as _instance_port, url as _instance_url
import argparse, json, os, queue, re, subprocess, threading, time, urllib.request, urllib.error, shlex
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter.scrolledtext import ScrolledText

SYSTEM_FALLBACK='You are PortableAI. Use the supplied tools when needed. Prefer documented Agent/ai_tools.py commands.'

def post_json(url,payload,timeout=1800):
    req=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=timeout) as r: return json.loads(r.read().decode('utf-8'))

def get_json(url,timeout=5):
    with urllib.request.urlopen(url,timeout=timeout) as r: return json.loads(r.read().decode('utf-8'))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--root',required=True); ns=ap.parse_args(); root=Path(ns.root).resolve()
    sessions=root/'Data'/'Sessions'; sessions.mkdir(parents=True,exist_ok=True)
    candidates=list(root.glob('PortableAI_Master_Instructions*.txt')) + list(root.glob('PortableAI_Master_Instructions*.md'))
    def _master_key(p):
        m=re.search(r'(?:^|[_-])v(\d+)(?:[_.-](\d+))?', p.stem, re.I)
        return (int(m.group(1)) if m else -1, int(m.group(2) or 0) if m else -1, p.stat().st_mtime)
    master=max(candidates,key=_master_key) if candidates else None
    system=master.read_text('utf-8',errors='ignore') if master else SYSTEM_FALLBACK
    api=_instance_url('qwen', '/v1')
    try:
        models=get_json(api+'/models').get('data',[]); model=models[0].get('id','local-model') if models else 'local-model'
    except Exception: model='local-model'

    app=tk.Tk(); app.title('PortableAI Chat'); app.geometry('1100x760'); app.minsize(760,520)
    bg='#111315'; panel='#1c1e20'; text='#f2ece2'; gold='#a87d32'; accent='#58afc1'; muted='#b7afa4'
    app.configure(bg=bg)
    top=tk.Frame(app,bg=panel,highlightthickness=1,highlightbackground=gold); top.pack(fill='x')
    tk.Label(top,text='PortableAI Chat',bg=panel,fg=text,font=('Segoe UI',14,'bold')).pack(side='left',padx=12,pady=9)
    status=tk.Label(top,text=f'Qwen · {model}',bg=panel,fg=accent,font=('Segoe UI',9)); status.pack(side='right',padx=12)
    transcript=ScrolledText(app,bg=bg,fg=text,insertbackground=text,wrap='word',font=('Segoe UI',10),bd=0,padx=14,pady=12); transcript.pack(fill='both',expand=True,padx=8,pady=8); transcript.configure(state='disabled')
    bottom=tk.Frame(app,bg=panel); bottom.pack(fill='x',padx=8,pady=(0,8))
    prompt=tk.Text(bottom,height=4,bg='#242628',fg=text,insertbackground=text,wrap='word',bd=0,padx=10,pady=8); prompt.pack(side='left',fill='x',expand=True,padx=(0,8))
    send=tk.Button(bottom,text='Send',bg=gold,fg='white',bd=0,padx=20,command=lambda: submit()); send.pack(side='right',fill='y')
    messages=[{'role':'system','content':system}]

    def add(role,content):
        transcript.configure(state='normal'); transcript.insert('end',f'\n{role}\n',('role',)); transcript.insert('end',str(content)+'\n'); transcript.tag_config('role',foreground=accent,font=('Segoe UI',10,'bold')); transcript.configure(state='disabled'); transcript.see('end')

    def safe_path(s):
        p=Path(s); p=(root/p).resolve() if not p.is_absolute() else p.resolve()
        if root not in p.parents and p!=root: raise PermissionError('Path is outside PortableAI root')
        return p
    def tool_shell(command):
        # OpenGUI-compatible shell surface, constrained to PortableAI cwd.
        # IMPORTANT: never resolve bare `python`/`py` from the host PATH.
        # Agent orchestration scripts run under BootstrapPython; bridges select
        # their own frozen component runtimes for ML workloads.
        boot = root/'Runtime'/'BootstrapPython'/'python.exe'
        c = command.strip()
        m = re.match(r'(?is)^\s*(?:python(?:\.exe)?|py(?:\.exe)?(?:\s+-3(?:\.\d+)?)?)\s+(.+)$', c)
        if m:
            if not boot.exists():
                raise FileNotFoundError('Portable BootstrapPython is missing')
            c = subprocess.list2cmdline([str(boot)]) + ' ' + m.group(1)
        cp=subprocess.run(c,cwd=root,shell=True,capture_output=True,text=True,timeout=1800,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),env=portable_env(root))
        return (cp.stdout+('\n'+cp.stderr if cp.stderr else ''))[-30000:]

    def portable_env(root):
        env=os.environ.copy()
        boot=root/'Runtime'/'BootstrapPython'
        env['PYTHONNOUSERSITE']='1'; env['PYTHONHOME']=str(boot); env.pop('PYTHONPATH',None)
        env['PATH']=str(boot)+os.pathsep+env.get('PATH','')
        tmp=root/'Agent'/'.runtime'/'tmp'; tmp.mkdir(parents=True,exist_ok=True)
        env['TEMP']=str(tmp); env['TMP']=str(tmp)
        return env
    def tool_read(path): return safe_path(path).read_text('utf-8',errors='replace')[:60000]
    def tool_write(path,content): p=safe_path(path); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(content,'utf-8'); return f'wrote {p}'
    def tool_edit(path,old,new):
        p=safe_path(path); s=p.read_text('utf-8');
        if old not in s: raise ValueError('old text not found')
        p.write_text(s.replace(old,new,1),'utf-8'); return f'edited {p}'
    funcs={'shell':lambda a:tool_shell(a['command']),'read_file':lambda a:tool_read(a['path']),'write_file':lambda a:tool_write(a['path'],a['content']),'edit_file':lambda a:tool_edit(a['path'],a['old'],a['new'])}
    tools=[
      {'type':'function','function':{'name':'shell','description':'Run a PortableAI command from the PortableAI root. Use documented .\\Tools\\portable_python.cmd Agent\\ai_tools.py commands for media/AI work.','parameters':{'type':'object','properties':{'command':{'type':'string'}},'required':['command']}}},
      {'type':'function','function':{'name':'read_file','description':'Read a text file inside PortableAI.','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}},
      {'type':'function','function':{'name':'write_file','description':'Write a text file inside PortableAI.','parameters':{'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'}},'required':['path','content']}}},
      {'type':'function','function':{'name':'edit_file','description':'Replace one exact text occurrence in a file inside PortableAI.','parameters':{'type':'object','properties':{'path':{'type':'string'},'old':{'type':'string'},'new':{'type':'string'}},'required':['path','old','new']}}},
    ]
    def agent_turn():
        try:
            status.configure(text='Thinking…')
            for _ in range(12):
                data=post_json(api+'/chat/completions',{'model':model,'messages':messages,'tools':tools,'tool_choice':'auto','temperature':0.4})
                msg=data['choices'][0]['message']; messages.append(msg)
                calls=msg.get('tool_calls') or []
                if not calls:
                    content=msg.get('content') or ''; app.after(0,lambda c=content:add('Qwen',c)); break
                for call in calls:
                    name=call['function']['name']; raw=call['function'].get('arguments','{}')
                    try: args=json.loads(raw) if isinstance(raw,str) else raw; result=funcs[name](args)
                    except Exception as e: result=f'ERROR: {type(e).__name__}: {e}'
                    app.after(0,lambda n=name,r=result:add('Tool · '+n,r[-4000:]))
                    messages.append({'role':'tool','tool_call_id':call['id'],'content':result})
            else: app.after(0,lambda:add('System','Tool-call limit reached.'))
        except Exception as e: app.after(0,lambda:add('Error',repr(e)))
        finally: app.after(0,lambda:status.configure(text=f'Qwen · {model}'))
    def submit(event=None):
        s=prompt.get('1.0','end').strip()
        if not s:return 'break'
        prompt.delete('1.0','end'); messages.append({'role':'user','content':s}); add('You',s); threading.Thread(target=agent_turn,daemon=True).start(); return 'break'
    prompt.bind('<Control-Return>',submit)
    app.mainloop(); return 0
if __name__=='__main__': raise SystemExit(main())
