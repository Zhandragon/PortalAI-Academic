"""Prepare automatic HA YAML changes, without constructing !secret/!include tags.

Only the PortalAI integration/panel and frontend/Lovelace sections are rewritten.
Unrelated sections retain their original bytes; all changed files are journaled.
Complex includes/aliases in edited sections fail before installation, never guess.
"""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'vendor'))
import yaml
from yaml.nodes import MappingNode, SequenceNode, ScalarNode

DOMAINS=('portalai_projection','portalai_native','portalai_recovery')
MODULES=('/local/portalai-quick-chat-v0.4.3.js','/local/portalai-projection-v0.5.11.js')

def node(value):
    return yaml.compose(yaml.safe_dump(value,sort_keys=False,allow_unicode=True),Loader=yaml.SafeLoader)

def mapping(n,label):
    if isinstance(n,ScalarNode) and n.tag=='tag:yaml.org,2002:null':
        return node({})
    if not isinstance(n,MappingNode) or n.tag!='tag:yaml.org,2002:map':
        raise ValueError(label+' must be an inline YAML mapping for automatic setup. Use --files-only and the generated examples for custom !include layouts.')
    keys=[k.value for k,v in n.value]
    if len(keys)!=len(set(keys)) or '<<' in keys:
        raise ValueError('Duplicate/merged YAML keys in '+label+'; no files changed.')
    return n

def get(n,key,default=None):
    return next((v for k,v in n.value if k.value==key),default)

def put(n,key,value):
    for i,(k,v) in enumerate(n.value):
        if k.value==key:n.value[i]=(k,value);return
    n.value.append((node(key),value))

def sequence(n,label):
    if not isinstance(n,SequenceNode) or n.tag!='tag:yaml.org,2002:seq':
        raise ValueError(label+' must be an inline list for automatic setup; use --files-only for a custom include layout.')
    return n

def configure(text,device_id):
    # Reject aliases rather than rewrite a value shared with an unrelated section.
    if any(isinstance(t,(yaml.tokens.AnchorToken,yaml.tokens.AliasToken)) for t in yaml.scan(text)):
        raise ValueError('YAML anchors/aliases require manual merge (--files-only); nothing installed.')
    original=yaml.compose(text,Loader=yaml.SafeLoader)
    if original is None:original=node({})
    root=mapping(original,'configuration.yaml')
    # Packages may define duplicate panels/resources outside this file. Do not
    # pretend a local merge can resolve an arbitrary external configuration.
    home=get(root,'homeassistant')
    if home and (not isinstance(home,MappingNode) or get(home,'packages') is not None):
        raise ValueError('Existing Home Assistant packages/includes need manual merge (--files-only); no files changed.')
    current={k.value:(k,v) for k,v in root.value}
    changed={}
    for domain in DOMAINS:
        if domain not in current:changed[domain]=node({})
    front=mapping(get(root,'frontend',node({})),'frontend')
    modules=sequence(get(front,'extra_module_url',node([])),'frontend.extra_module_url')
    modules.value=[v for v in modules.value if not (isinstance(v,ScalarNode) and v.value.startswith(('/local/portalai-quick-chat-','/local/portalai-projection-')))]
    modules.value.extend(node(url) for url in MODULES);put(front,'extra_module_url',modules);changed['frontend']=front
    panels=sequence(get(root,'panel_custom',node([])),'panel_custom')
    kept=[]
    for p in panels.value:
        p=mapping(p,'panel_custom entry');name=get(p,'name');url=get(p,'url_path')
        if name and name.value=='portalai-live-panel':continue
        if url and url.value=='portalai-native':raise ValueError('portalai-native URL belongs to a different custom panel.')
        kept.append(p)
    panels.value=kept+[node({'name':'portalai-live-panel','sidebar_title':'PortalAI Native','sidebar_icon':'mdi:monitor-dashboard','url_path':'portalai-native','module_url':'/local/portalai-live-v0.5.11.js','require_admin':True,'config':{'device_id':device_id}})]
    changed['panel_custom']=panels
    lovelace=mapping(get(root,'lovelace',node({})),'lovelace')
    dashboards=mapping(get(lovelace,'dashboards',node({})),'lovelace.dashboards')
    prior=get(dashboards,'portalai-overview')
    if prior is not None:
        filename=get(mapping(prior,'portalai-overview'),'filename')
        if not filename or filename.value!='portalai/dashboard.yaml':raise ValueError('portalai-overview is already owned by another dashboard.')
    put(dashboards,'portalai-overview',node({'mode':'yaml','title':'PortalAI','icon':'mdi:robot','show_in_sidebar':True,'require_admin':True,'filename':'portalai/dashboard.yaml'}))
    put(lovelace,'dashboards',dashboards);changed['lovelace']=lovelace
    # Capture complete top-level entry boundaries using parser marks. Values
    # may be inline or block; replace only sections deliberately edited above.
    replacements=[];additions=[]
    newline='\r\n' if '\r\n' in text else '\n'
    for key,value in changed.items():
        rendered=yaml.serialize(MappingNode('tag:yaml.org,2002:map',[(node(key),value)]),allow_unicode=True).rstrip()+'\n'
        rendered=rendered.replace('\n',newline)
        if key in current:
            k,v=current[key];end=v.end_mark.index
            # A flow value leaves the remainder of its line (including comment).
            if end<len(text) and v.end_mark.column>0 and text[end:end+1] not in ('\n','\r'):
                lineend=text.find('\n',end);end=len(text) if lineend<0 else lineend+1
            elif end<len(text) and v.end_mark.column>0 and text[end:end+1] in ('\n','\r'):
                end=text.find('\n',end)+1
            replacements.append((k.start_mark.index,end,rendered))
        else:additions.append(rendered)
    for start,end,data in sorted(replacements,reverse=True):text=text[:start]+data+text[end:]
    if additions:text=text.rstrip('\r\n')+newline+newline+''.join(additions)
    mapping(yaml.compose(text,Loader=yaml.SafeLoader),'result')
    return text

def dashboard(device_id):
    recovery={'type':'vertical-stack','cards':[
        {'type':'button','name':'Recover PortalAI apps','icon':'mdi:lifebuoy','tap_action':{'action':'perform-action','perform_action':'portalai_recovery.recover_apps','data':{'device_id':device_id},'confirmation':{'text':'Restore projection and open normal PortalAI login?'}}},
        {'type':'entity','entity':'sensor.portalai_recovery_'+device_id[:8],'name':'Recovery helper (separate pairing required)'}]}
    value={'title':'PortalAI','views':[
        {'title':'Quick Chat','path':'chat','cards':[
            {'type':'markdown','content':'[Open Native UI](/portalai-native) · Attach files and use the full PortalAI controls.'},
            {'type':'custom:portalai-quick-chat','title':'PortalAI','device_id':device_id}]},
        {'title':'Desktop','path':'desktop','panel':True,'cards':[{'type':'custom:portalai-projection','title':'PortalAI desktop','device_id':device_id}]},
        {'title':'Recovery','path':'recovery','cards':[{'type':'markdown','content':'Recovery requires the separate Windows helper to be paired and armed. See RECOVERY.txt. No applications restart automatically.'},recovery]}]}
    return yaml.safe_dump(value,sort_keys=False,allow_unicode=True)
