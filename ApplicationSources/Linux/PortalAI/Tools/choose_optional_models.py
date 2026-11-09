"""Native installer model choices. Downloads happen only after explicit review."""
import argparse
import json
from pathlib import Path
import sys
import threading
import webbrowser

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Tools')]
from model_choices import validate_custom_request


def catalog(root=ROOT):
    from import_foundation_assets import ASSETS
    academic=(root/'Agent/academic_policy.py').exists()
    return [a for a in ASSETS if a['id'] in (
        'qwen1.7-q8','qwen1.7-abliterated-q8','qwen4-q4','qwen4-abliterated-q4')
        and (not academic or 'abliterated' not in a['id'])]


def choose(root=ROOT):
    import tkinter as tk
    from tkinter import ttk,messagebox
    academic=(root/'Agent/academic_policy.py').exists()
    rows=catalog(root);result=[]
    app=tk.Tk();app.title('PortalAI · optional, suggested/supported models');app.geometry('850x850')
    app.configure(bg='#EEE7DC')
    body=ttk.Frame(app,padding=20);body.pack(fill='both',expand=True)
    ttk.Label(body,text='Choose the models for your workspace',font=('Segoe UI',18,'bold')).pack(anchor='w')
    ttk.Label(body,wraplength=790,text="The purchase covers PortalAI's harness. These optional, suggested/supported examples are separately licensed. All downloads are off until you choose them. Existing models are kept.").pack(fill='x',pady=10)
    choices={}
    for row in rows:
        v=tk.BooleanVar(value=False);choices[row['id']]=v
        ttk.Checkbutton(body,variable=v,text=f"{row['id']} · {row['size']/1024**3:.2f} GiB · Apache-2.0").pack(anchor='w',pady=3)
    ttk.Label(body,wraplength=790,text='Apache-2.0 permits commercial use subject to its terms, including notices. Abliterated variants have reduced refusal behavior and can still make mistakes. PortalAI is not an isolation sandbox.').pack(fill='x',pady=8)
    sources=tk.Text(body,height=5,wrap='word');sources.pack(fill='x')
    sources.insert('1.0','Publisher: https://huggingface.co/Qwen/Qwen3-1.7B\n\n'+'\n'.join(row['id']+': '+row['url'] for row in rows));sources.configure(state='disabled')
    ttk.Button(body,text='Open publisher / license',command=lambda:webbrowser.open('https://huggingface.co/Qwen/Qwen3-1.7B')).pack(anchor='w',pady=5)
    use_custom=tk.BooleanVar(value=False)
    ttk.Checkbutton(body,text='Use my own compatible chat model',variable=use_custom).pack(anchor='w',pady=(12,5))
    ttk.Label(body,wraplength=790,text='Different single-file dense Qwen3 GGUF text models are supported after validation. Uncheck the suggestions to install only yours. Vision, media and adapters need their own workflow contracts.').pack(fill='x')
    grid=ttk.Frame(body);grid.pack(fill='x',pady=6);grid.columnconfigure(1,weight=1)
    fields={}
    for i,(key,label) in enumerate((('label','Display name'),('url','Direct HTTPS .gguf URL'),('sha256','Publisher SHA-256'),('bytes','Exact byte size'),('license_url','Publisher license URL'))):
        ttk.Label(grid,text=label).grid(row=i,column=0,sticky='w',padx=(0,15),pady=4)
        v=tk.StringVar();fields[key]=v;ttk.Entry(grid,textvariable=v).grid(row=i,column=1,sticky='ew',pady=4)
    variant=tk.StringVar(value='standard')
    ttk.Label(grid,text='Variant').grid(row=5,column=0,sticky='w')
    ttk.Combobox(grid,textvariable=variant,values=['standard'] if academic else ['standard','uncensored'],state='readonly').grid(row=5,column=1,sticky='ew')
    accepted=tk.BooleanVar(value=False)
    ttk.Checkbutton(body,text='I reviewed the selected models\' licenses and sources and am authorized to use them.',variable=accepted).pack(anchor='w',pady=10)
    status=tk.StringVar(value='No models are required to install the harness. Select an installed model in Settings before using Chat.')
    ttk.Label(body,textvariable=status,wraplength=790).pack(fill='x',pady=5)
    def finish():
        try:
            selected=[key for key,v in choices.items() if v.get()]
            custom=None
            if (selected or use_custom.get()) and not accepted.get():
                raise ValueError('Review and acknowledge the selected model licenses first.')
            if use_custom.get():
                custom={key:v.get().strip() for key,v in fields.items()}
                custom.update(bytes=int(custom['bytes']),sha256=custom['sha256'].lower(),variant=variant.get(),accepted=True)
                custom=validate_custom_request(custom,academic=academic)
            result.append({'selected':selected,'accepted':accepted.get(),'custom':custom});app.destroy()
        except (ValueError,TypeError) as exc:messagebox.showerror('Check model choices',str(exc),parent=app)
    bar=ttk.Frame(body);bar.pack(fill='x',pady=8)
    ttk.Button(bar,text='Continue with these choices',command=finish).pack(side='right')
    ttk.Button(bar,text='Cancel installation',command=app.destroy).pack(side='right',padx=10)
    app.mainloop()
    if not result:raise RuntimeError('Model selection cancelled; no models downloaded.')
    return result[0]


def install_choices(request, root=ROOT):
    from import_foundation_assets import ASSETS,install
    selected=request.get('selected',[]);rows={a['id']:a for a in catalog(root)}
    if not isinstance(selected,list) or len(set(selected))!=len(selected) or set(selected)-rows.keys():
        raise ValueError('Unknown or disallowed suggested model')
    custom=request.get('custom')
    if (selected or custom) and request.get('accepted') is not True:
        raise ValueError('Model licenses must be reviewed before download')
    if custom:
        custom=validate_custom_request(custom,academic=(root/'Agent/academic_policy.py').exists())
        if (root/'Agent/academic_policy.py').exists():
            from academic_policy import require_asset
            require_asset(custom)
    for key in selected:install(rows[key],root)
    if selected:install(next(a for a in ASSETS if a['id']=='qwen-license'),root)
    if custom:
        from installer_core import fetch,checked_path,sha256
        from custom_models import inspect_gguf
        from runtime_policy import require_space,atomic_json
        pin=custom['sha256'];require_space(root,custom['bytes']*2+1024**3)
        file=fetch({'id':'custom-'+pin,'url':custom['url'],'bytes':custom['bytes'],'sha256':pin},
                   checked_path(root,'Cache/model-downloads'),threading.Event(),lambda label,done,total:print(label,done,total,flush=True))
        inspect_gguf(file)
        target=checked_path(root,'LLM/custom/'+pin+'.gguf');target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            if target.stat().st_size!=custom['bytes'] or sha256(target)!=pin:raise ValueError('Existing custom model differs; no file was overwritten')
        else:
            import shutil,uuid
            stage=target.with_name(target.name+'.'+uuid.uuid4().hex+'.partial')
            with file.open('rb') as source,stage.open('xb') as output:shutil.copyfileobj(source,output,1024**2)
            if sha256(stage)!=pin:raise ValueError('Custom model readback failed')
            stage.rename(target)
        receipt=checked_path(root,'Maintenance/Imports/custom-'+pin+'.json')
        atomic_json(receipt,{'schema':1,'kind':'portalai-custom-model','request':custom,'path':'LLM/custom/'+pin+'.gguf','verified':True})
    return {'suggested':selected,'custom':bool(custom)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--choices',type=Path)
    args=parser.parse_args()
    request=json.loads(args.choices.read_text('utf-8')) if args.choices else choose()
    print(json.dumps(install_choices(request)),flush=True)

if __name__=='__main__':main()
