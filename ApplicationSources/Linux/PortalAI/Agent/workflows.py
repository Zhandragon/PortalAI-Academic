"""Versioned, bounded workflows with durable step receipts and explicit approvals.

Templates are data, never Python. No service, scheduler or background retry is
created. A saved run retains its original template even after an editor changes it.
"""
import copy
import re
import time
from workspace_store import Workspace, identifier, read_json, encoded, digest

KINDS={'knowledge','mcp','tool','prompt','condition','approval','output'}
TOOLS={'read_file','write_file','edit_file','list_dir','science','web','media_tool','generate_image'}


def validate(template):
    if not isinstance(template,dict) or template.get('version')!=1:raise ValueError('Workflow version must be 1')
    if not isinstance(template.get('name'),str) or not 1<=len(template['name'].strip())<=120:raise ValueError('Workflow needs a name of 1–120 characters')
    inputs=template.get('inputs',[])
    if not isinstance(inputs,list) or len(inputs)>32 or any(not isinstance(k,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,39}',k) for k in inputs) or len(set(inputs))!=len(inputs):raise ValueError('Inputs must be up to 32 unique field names')
    steps=template.get('steps')
    if not isinstance(steps,list) or not 1<=len(steps)<=64:raise ValueError('Use 1–64 workflow steps')
    names=[]
    for step in steps:
        if not isinstance(step,dict) or step.get('kind') not in KINDS:raise ValueError('Unknown workflow step kind')
        name=step.get('id')
        if not isinstance(name,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,39}',name) or name in names:raise ValueError('Steps need unique field-style IDs')
        names.append(name)
        if not isinstance(step.get('arguments',{}),dict):raise ValueError('Step arguments must be an object')
        if step['kind']=='tool' and step.get('tool') not in TOOLS:raise ValueError('Workflow tool is not supported')
        if step['kind']=='condition' and step.get('operator','equals') not in ('equals','not_equals','contains','truthy'):raise ValueError('Unknown condition operator')
    for i,step in enumerate(steps):
        if step['kind']=='condition':
            for key in ('then','else'):
                target=step.get(key)
                if target!='end' and (target not in names or names.index(target)<=i):raise ValueError('Conditions must branch forward to a step ID or end')
    if len(encoded(template))>128*1024:raise ValueError('Workflow template exceeds 128 KiB')
    return copy.deepcopy(template)


def resolve(value,environment):
    if isinstance(value,dict):
        if set(value)=={'$ref'}:
            parts=str(value['$ref']).split('.')
            if parts[0] not in ('inputs','steps'):raise ValueError('References start with inputs or steps')
            result=environment
            for part in parts:
                if isinstance(result,dict) and part in result:result=result[part]
                elif isinstance(result,list) and part.isdigit() and int(part)<len(result):result=result[int(part)]
                else:raise ValueError('Unresolved workflow reference: '+str(value['$ref']))
            return copy.deepcopy(result)
        return {k:resolve(v,environment) for k,v in value.items()}
    if isinstance(value,list):return [resolve(v,environment) for v in value]
    return value


class Workflows(Workspace):
    def __init__(self,root,check=None,execute=None):
        super().__init__(root,'Workflows',check);self.executor=execute

    def templates(self):return [self.template(tid) for tid in self.records('Templates')]
    def template(self,tid):return validate(read_json(self.path('Templates/'+identifier(tid)+'.json')))
    def put(self,template,tid=None):
        row=validate(template);row['id']=identifier(tid) if tid else self.new_id();row['updated_at']=time.time()
        with self.lock(row['id']):self.save('Templates/'+row['id']+'.json',row)
        return row
    def run(self,rid):
        row=read_json(self.path('Runs/'+identifier(rid)+'.json'))
        if row.get('id')!=rid or row['template_hash']!=digest(row['template']):raise ValueError('Workflow checkpoint identity mismatch')
        validate(row['template']);return row
    def runs(self):return [self.run(rid) for rid in self.records('Runs')]
    def _save(self,row):
        row['updated_at']=time.time();self.save('Runs/'+row['id']+'.json',row)

    def start(self,tid,inputs):
        template=self.template(tid)
        if not isinstance(inputs,dict) or set(inputs)!=set(template.get('inputs',[])):raise ValueError('Provide exactly the template input fields')
        if len(encoded(inputs))>64*1024:raise ValueError('Workflow inputs exceed 64 KiB')
        row={'id':self.new_id(),'template':template,'template_hash':digest(template),'inputs':inputs,'cursor':0,
             'results':{},'attempts':{},'state':'ready','pending':None,'approvals':[],'created_at':time.time()}
        self._save(row);return row

    def advance(self,rid):
        with self.lock(identifier(rid)):
            row=self.run(rid)
            if row['state']=='complete':return row
            if row.get('pending'):raise RuntimeError('An earlier step may have had effects; review the saved run before continuing')
            steps=row['template']['steps'];deadline=time.monotonic()+600
            while row['cursor']<len(steps):
                self.check()
                if time.monotonic()>deadline:row['state']='paused';self._save(row);return row
                step=steps[row['cursor']];sid=step['id'];kind=step['kind']
                if kind=='approval' and sid not in row['approvals']:
                    row['state']='approval';self._save(row);return row
                count=row['attempts'].get(sid,0)
                if count>=3:raise RuntimeError('Step exhausted its three attempts; create a new reviewed run')
                env={'inputs':row['inputs'],'steps':row['results']}
                args=resolve(step.get('arguments',{}),env);row['attempts'][sid]=count+1
                row['state']='running';row.pop('error',None)
                # Treat every external tool as effectful. Even read-only hints
                # supplied by a server are insufficient to authorize replay.
                effect=kind in ('mcp','tool')
                if effect:row['pending']={'step':sid,'kind':kind,'arguments':args,'at':time.time()}
                self._save(row)
                try:
                    if kind=='condition':
                        left=resolve(step.get('left'),env);right=resolve(step.get('right'),env);op=step.get('operator','equals')
                        answer=(left==right if op=='equals' else left!=right if op=='not_equals' else right in left if op=='contains' else bool(left))
                        target=step['then' if answer else 'else'];result={'condition':bool(answer),'next':target}
                    elif kind=='approval':result={'approved_by_user':True}
                    elif kind=='output':result=resolve(step.get('value',args),env)
                    else:
                        if self.executor is None:raise RuntimeError('Workflow execution requires the authenticated tool runtime')
                        result=self.executor(kind,step,args,rid+':'+sid)
                        if isinstance(result,str) and result.lstrip().startswith('ERROR:'):raise RuntimeError(result[:2000])
                        if isinstance(result,dict) and result.get('isError'):raise RuntimeError('Tool returned an error: '+str(result)[:2000])
                    if len(encoded(result))>16000:raise ValueError('Step result exceeds 16 KiB; narrow the requested output')
                    self.check();row['results'][sid]=result;row['pending']=None
                    if kind=='condition':row['cursor']=len(steps) if target=='end' else next(i for i,s in enumerate(steps) if s['id']==target)
                    else:row['cursor']+=1
                    row['state']='ready';self._save(row)
                except Exception as exc:
                    row['state']='review' if effect else 'paused';row['error']=str(exc)[:2000]
                    self._save(row);raise
            row['state']='complete';self._save(row);return row

    def approve(self,rid):
        """Management UI only; never exposed to the model tool catalogue."""
        with self.lock(identifier(rid)):
            row=self.run(rid)
            if row['state']!='approval':raise ValueError('This run is not waiting for approval')
            sid=row['template']['steps'][row['cursor']]['id'];row['approvals'].append(sid);row['state']='ready';self._save(row)
        return row

    def review(self,rid,decision,result=None):
        with self.lock(identifier(rid)):
            row=self.run(rid)
            if not row.get('pending'):raise ValueError('No uncertain step to review')
            if decision=='confirmed':
                if len(encoded(result))>16000:raise ValueError('Reviewed result exceeds 16 KiB')
                row['results'][row['pending']['step']]=result;row['cursor']+=1
            elif decision!='allow_retry':raise ValueError('Choose confirmed or allow_retry')
            row.setdefault('reviews',[]).append({'pending':row['pending'],'decision':decision,'at':time.time()})
            row['pending']=None;row['state']='ready';self._save(row)
        return row


EXAMPLE={'version':1,'name':'Search a collection and review the answer','inputs':['question'], 'steps':[
    {'id':'search','kind':'knowledge','arguments':{'action':'search','query':{'$ref':'inputs.question'},'limit':4}},
    {'id':'draft','kind':'prompt','arguments':{'question':{'$ref':'inputs.question'},'context':{'$ref':'steps.search'}}},
    {'id':'review','kind':'approval'},
    {'id':'answer','kind':'output','value':{'$ref':'steps.draft'}}]}
