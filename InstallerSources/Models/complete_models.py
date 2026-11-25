"""Optional model downloads for native Mac/Linux installers.

Uses the same reviewed file inventory as Windows, with OS-specific runtime
packages removed. No download or publisher agreement is automatic.
"""
from pathlib import Path
import argparse, copy, hashlib, json, os, shutil, subprocess, sys, threading, uuid

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'Engine'))
import installer_core as core
from installer_storage import check_space
from model_choices import validate_consent


def manifest(catalog):
    return dict(schema=1,status='RELEASED',model_choice_policy=1,components=catalog['components'],
        payload=dict(bytes=0,sha256=hashlib.sha256(b'').hexdigest(),format='zip',members=[]))


def chosen(catalog, selected):
    return core.plan(manifest(catalog),selected)


def install(root, package, catalog, request, token='', opener=None):
    root=core.native_path(root).resolve();package=core.native_path(package).resolve()
    if catalog.get('schema')!=1 or catalog.get('edition') not in ('Full','Academic'):
        raise ValueError('Invalid model catalog')
    academic=(root/'Agent/academic_policy.py').is_file()
    if academic != (catalog['edition']=='Academic'):
        raise ValueError('Model catalog edition does not match the installed application')
    selected=request['selected']
    groups,artifacts,files,_=chosen(catalog,selected)
    validate_consent(manifest(catalog),groups,selected,request.get('consent'))
    core.set_huggingface_token(token)
    stop=threading.Event()
    def local(row):
        prefix='PortalAI Windows/'
        if not row['dest'].startswith(prefix):raise ValueError('Model path is outside the application')
        core.public_destination(row['dest'])
        return {**row,'dest':row['dest'][len(prefix):]}
    local_files=[local(r) for r in files]
    missing=set()
    for row in local_files:
        target=core.checked_path(root,row['dest'])
        if target.exists():
            if not target.is_file() or target.stat().st_size!=row['bytes'] or core.sha256(target)!=row['sha256']:
                raise ValueError('Existing model differs; no files were overwritten: '+row['dest'])
        else:missing.add(row['dest'])
    needed=[a for a in artifacts if any(local(r)['dest'] in missing for r in a['members'])]
    check_space(root,[r for r in local_files if r['dest'] in missing],needed)
    cache=core.checked_path(root,'Cache/model-downloads');cache.mkdir(parents=True,exist_ok=True)
    stage=core.checked_path(root,'Cache/model-stage-'+uuid.uuid4().hex);stage.mkdir()
    try:
        for artifact in needed:
            rows=[local(r) for r in artifact['members'] if local(r)['dest'] in missing]
            print('Downloading / checking '+artifact['id'],flush=True)
            if opener is not None and 'bundled_file' not in artifact:
                source=core.fetch(artifact,cache,stop,lambda *args:None,opener=opener)
            else:source=core.download_artifact(artifact,package,cache,stop,lambda *args:None)
            if artifact['format']=='file':
                with source.open('rb') as stream:core.write_verified(stream,core.checked_path(stage,rows[0]['dest']),rows[0],stop)
            elif artifact['format']=='zip':core.extract_allowlist(source,rows,stage,stop)
            elif artifact['format']=='tar':core.extract_tar_allowlist(source,rows,stage,stop)
            else:raise ValueError('Native model catalog contains an OS-specific executable package')
        for row in local_files:
            if row['dest'] not in missing:continue
            source=core.checked_path(stage,row['dest'])
            if source.stat().st_size!=row['bytes'] or core.sha256(source)!=row['sha256']:
                raise ValueError('Model readback failed')
        # Link within the destination filesystem: publish complete files atomically
        # and fail if another process created the target in the meantime.
        for row in local_files:
            if row['dest'] not in missing:continue
            target=core.checked_path(root,row['dest']);target.parent.mkdir(parents=True,exist_ok=True)
            os.link(core.checked_path(stage,row['dest']),target)
        receipt=core.checked_path(root,'Maintenance/Imports/complete-model-catalog-'+uuid.uuid4().hex+'.json')
        receipt.parent.mkdir(parents=True,exist_ok=True)
        receipt.write_text(json.dumps(dict(schema=1,version=catalog['version'],selected=selected,files=local_files,verified=True),indent=2)+'\n',encoding='utf-8')
        core.completed_download_cleanup(cache,needed,lambda message,*args:print(message,flush=True))
        return dict(models=len(groups),files=len(files),new_files=len(missing))
    finally:
        core.set_huggingface_token('')
        if not stage.resolve().is_relative_to((root/'Cache').resolve()) or not stage.name.startswith('model-stage-'):
            raise ValueError('Unexpected model staging path')
        shutil.rmtree(stage)


def choose(catalog):
    import tkinter as tk
    from tkinter import ttk,messagebox
    window=tk.Tk();window.title('PortalAI · optional model downloads');window.geometry('920x790');window.minsize(760,650)
    body=ttk.Frame(window,padding=18);body.pack(fill='both',expand=True)
    ttk.Label(body,text='Choose models to download',font=('Helvetica',18,'bold')).pack(anchor='w')
    ttk.Label(body,text='All models are optional. Select all to recreate the complete model collection, or choose individual groups.\n'+catalog['notice'],wraplength=860).pack(fill='x',pady=8)
    pane=ttk.Frame(body);pane.pack(fill='both',expand=True)
    listing=tk.Listbox(pane,selectmode='multiple',exportselection=False,height=13)
    scrollbar=ttk.Scrollbar(pane,command=listing.yview);listing.configure(yscrollcommand=scrollbar.set)
    scrollbar.pack(side='right',fill='y');listing.pack(side='left',fill='both',expand=True)
    rows=catalog['components']
    for row in rows:
        size=sum(a['bytes'] for a in row['artifacts'])/1024**3
        listing.insert('end',f"{row['label']} · {size:.2f} GiB · {row['model_choice']['license']}")
    buttons=ttk.Frame(body);buttons.pack(fill='x',pady=5)
    total=tk.StringVar(value='No models selected. No downloads have started.')
    details=tk.Text(body,height=9,wrap='word');details.pack(fill='both',expand=True)
    def update(event=None):
        selected=[rows[i]['id'] for i in listing.curselection()]
        groups,artifacts,files,_=chosen(catalog,selected)
        expanded={c['id'] for c in groups}
        for i,row in enumerate(rows):
            if row['id'] in expanded:listing.selection_set(i)
        total.set(f'{len(groups)} groups · {sum({a["sha256"]:a["bytes"] for a in artifacts}.values())/1024**3:.2f} GiB download; temporary space is checked before downloading.')
        details.configure(state='normal');details.delete('1.0','end')
        for row in groups:
            r=row['model_choice'];details.insert('end',row['label']+'\n'+r['license']+'\n'+r['restrictions']+'\n'+r['license_url']+'\n\n')
        details.configure(state='disabled')
    listing.bind('<<ListboxSelect>>',update)
    def select_all():listing.selection_set(0,'end');update()
    def clear():listing.selection_clear(0,'end');update()
    ttk.Button(buttons,text='Select all models',command=select_all).pack(side='left')
    ttk.Button(buttons,text='Clear selections',command=clear).pack(side='left',padx=8)
    ttk.Label(body,textvariable=total,wraplength=860).pack(fill='x',pady=6)
    token=tk.StringVar();auth=ttk.Frame(body);auth.pack(fill='x')
    ttk.Label(auth,text='Your Hugging Face read token (optional; gated models only):').pack(side='left')
    ttk.Entry(auth,textvariable=token,show='*').pack(side='left',fill='x',expand=True)
    accepted=tk.BooleanVar(value=False);custom=tk.BooleanVar(value=False)
    ttk.Checkbutton(body,variable=accepted,text='I reviewed the selected models and dependencies above and am authorized to use them.').pack(anchor='w',pady=8)
    ttk.Checkbutton(body,variable=custom,text='Also open the custom GGUF model chooser').pack(anchor='w')
    result=[]
    def finish():
        selected=[rows[i]['id'] for i in listing.curselection()]
        groups,_,_,_=chosen(catalog,selected)
        if groups and not accepted.get():messagebox.showerror('Review model terms','Review and acknowledge the selected model terms before downloading.',parent=window);return
        result.append((dict(selected=selected,consent={c['id']:c['model_choice']['review_digest'] for c in groups},custom=custom.get()),token.get().strip()))
        token.set('');window.destroy()
    bar=ttk.Frame(body);bar.pack(fill='x',pady=10)
    ttk.Button(bar,text='Continue with these choices',command=finish).pack(side='right')
    ttk.Button(bar,text='Cancel installation',command=window.destroy).pack(side='right',padx=10)
    update();window.mainloop()
    if not result:raise RuntimeError('Model selection cancelled; no downloads started.')
    return result[0]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True,type=Path);parser.add_argument('--choices',type=Path)
    args=parser.parse_args();catalog=json.loads((HERE/'model-catalog.json').read_text('utf-8'))
    if args.choices:
        request=json.loads(args.choices.read_text('utf-8'));token=sys.stdin.readline(4097).strip()
    else:request,token=choose(catalog)
    result=install(args.root,HERE,catalog,request,token);token=''
    print(json.dumps(result),flush=True)
    if request.get('custom'):
        subprocess.run([sys.executable,'-B',str(args.root/'Tools/choose_optional_models.py')],check=True)

if __name__=='__main__':main()
