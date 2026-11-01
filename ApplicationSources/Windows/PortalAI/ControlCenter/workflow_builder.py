"""Native ordered-step editor for the existing durable workflow engine."""
import copy
import json
from tkinter import ttk
from internal_sheet import InternalSheet
from workflows import KINDS, validate

FIELDS = {
    'prompt': [('arguments.question','Question',''),('arguments.context','Context or @steps.search','')],
    'knowledge': [('arguments.action','Action','search'),('arguments.query','Search text or @inputs.question',''),('arguments.collection','Collection ID (optional)','')],
    'mcp': [('arguments.connection','Connection ID',''),('arguments.tool','Approved tool',''),('arguments.arguments','Tool arguments (=JSON object)','={}'),],
    'tool': [('tool','PortalAI tool','read_file'),('arguments','Tool arguments (=JSON object)','={}')],
    'condition': [('left','Left value or @inputs.name',''),('operator','equals / not_equals / contains / truthy','equals'),('right','Right value',''),('then','If true: later step ID or end','end'),('else','If false: later step ID or end','end')],
    'approval': [],
    'output': [('value','Output text, @steps.name or =JSON','')],
}


def typed(text):
    if text.startswith('@'): return {'$ref': text[1:]}
    if text.startswith('='): return json.loads(text[1:])
    return text


def display(value):
    if isinstance(value,dict) and set(value)=={'$ref'}:return '@'+value['$ref']
    if isinstance(value,str) and not value.startswith(('@','=')):return value
    return '='+json.dumps(value,ensure_ascii=False)


def update_step(previous, sid, kind, values):
    row=copy.deepcopy(previous) if previous.get('kind')==kind else {}
    row.update(id=sid,kind=kind)
    for path,value in values.items():
        parts=path.split('.');target=row
        if not value and path=='arguments.collection':
            if isinstance(row.get('arguments'),dict):row['arguments'].pop('collection',None)
            continue
        for part in parts[:-1]:target=target.setdefault(part,{})
        target[parts[-1]]=typed(value)
    return row


def open_builder(panel):
    panel.admin();draft=validate(json.loads(panel.editor.get('1.0','end')))
    sheet=InternalSheet(panel,'Workflow step editor',panel.skin.colors);skin=sheet.skin;p=sheet.content
    skin.label(p,'Add, edit and reorder steps. @inputs.name / @steps.name references a result; =true or ={...} supplies JSON. Saving validates the existing workflow rules.').pack(fill='x')
    skin.label(p,'Workflow name').pack(fill='x');name=skin.entry(p,draft['name']);name.pack(fill='x')
    skin.label(p,'Inputs (comma-separated names)').pack(fill='x');inputs=skin.entry(p,', '.join(draft.get('inputs',[])));inputs.pack(fill='x')
    tree=ttk.Treeview(p,columns=('order','id','kind'),show='headings',height=5,selectmode='browse')
    for key in ('order','id','kind'):tree.heading(key,text=key);tree.column(key,width=140)
    tree.pack(fill='x');sheet.style_tree(tree)
    skin.label(p,'Step type for new steps').pack(fill='x')
    kind=ttk.Combobox(p,values=sorted(KINDS),state='readonly');kind.set('prompt');kind.pack(fill='x')
    form=skin.frame(p);form.pack(fill='x');selected=[None];widgets={};id_entry=[None]
    def refresh(index=None):
        tree.delete(*tree.get_children())
        for i,row in enumerate(draft['steps']):tree.insert('','end',iid=str(i),values=(i+1,row['id'],row['kind']))
        if index is not None:tree.selection_set(str(index));edit()
    def edit(event=None):
        chosen=tree.selection()
        if not chosen:return
        i=int(chosen[0]);selected[0]=i;row=draft['steps'][i];widgets.clear()
        for child in form.winfo_children():child.destroy()
        skin.label(form,'Step ID').pack(fill='x');entry=skin.entry(form,row['id']);entry.pack(fill='x');id_entry[0]=entry
        for path,label,default in FIELDS[row['kind']]:
            value=row
            try:
                for part in path.split('.'):value=value[part]
                value=display(value)
            except (KeyError,TypeError):value=default
            skin.label(form,label).pack(fill='x');entry=skin.entry(form,value);entry.pack(fill='x');widgets[path]=entry
    def apply():
        if selected[0] is None:raise ValueError('Choose a step')
        i=selected[0];row=draft['steps'][i]
        candidate=update_step(row,id_entry[0].get().strip(),row['kind'],{k:v.get() for k,v in widgets.items()})
        if any(j!=i and r['id']==candidate['id'] for j,r in enumerate(draft['steps'])):raise ValueError('Step ID already exists')
        # Rename references together, including condition destinations.
        old=row['id'];new=candidate['id']
        def rename(value):
            if isinstance(value,dict):
                return {k: ('steps.'+new+v[len('steps.'+old):] if k=='$ref' and isinstance(v,str) and (v=='steps.'+old or v.startswith('steps.'+old+'.'))
                            else new if k in ('then','else') and v==old else rename(v)) for k,v in value.items()}
            if isinstance(value,list):return [rename(v) for v in value]
            return value
        draft['steps'][i]=candidate;draft['steps']=rename(draft['steps']);refresh(i)
    def add():
        if len(draft['steps'])>=64:raise ValueError('Workflow limit: 64 steps')
        number=1
        while 'step'+str(number) in {s['id'] for s in draft['steps']}:number+=1
        k=kind.get();draft['steps'].append(update_step({},'step'+str(number),k,{key:default for key,_,default in FIELDS[k]}));refresh(len(draft['steps'])-1)
    def move(delta):
        if selected[0] is None:return
        i=selected[0];j=i+delta
        if 0<=j<len(draft['steps']):draft['steps'][i],draft['steps'][j]=draft['steps'][j],draft['steps'][i];refresh(j)
    def remove():
        if selected[0] is None:return
        draft['steps'].pop(selected[0]);selected[0]=None;refresh(0 if draft['steps'] else None)
    def finish():
        if selected[0] is not None:apply()
        draft['name']=name.get();draft['inputs']=[v.strip() for v in inputs.get().split(',') if v.strip()]
        value=validate(draft);panel.editor.delete('1.0','end');panel.editor.insert('1.0',json.dumps(value,indent=2));sheet.destroy()
        panel.show('Workflow editor updated. Save it in Workflows to publish a new template revision; no step was executed.')
    tree.bind('<<TreeviewSelect>>',edit)
    from ui_extensions import ResponsiveFlow
    buttons=ResponsiveFlow(p,bg=skin.colors['panel'],hgap=4,vgap=4);buttons.pack(fill='x')
    for label,fn in [('Add step',add),('Apply step',apply),('Move up',lambda:move(-1)),('Move down',lambda:move(1)),('Remove step',remove),('Use this workflow',finish)]:
        buttons.add(skin.button(buttons,label,lambda f=fn:panel.invoke(f)))
    refresh(0)
