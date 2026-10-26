"""Structured SPICE and explicitly mapped through-hole PCB construction."""
import json,re,uuid
from Scientific.extensions_common import keys,number,integer,worker

def identifier(s):
    if not isinstance(s,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,32}',s):raise ValueError('Circuit identifiers must be 1..32 letters/digits/underscores')
    return s

def netlist(p):
    components=p['components'];models=p.get('models',[])
    if not isinstance(components,list) or not 1<=len(components)<=128:raise ValueError('Require 1..128 circuit components')
    if not isinstance(models,list) or len(models)>32:raise ValueError('At most 32 models')
    lines=['PortalAI bounded SPICE circuit'];defined={};refs=set();nodes=set()
    allowed={'D':{'IS','N','RS','CJO','VJ','M','TT','BV','IBV'},'NPN':{'IS','BF','BR','VAF','VAR','IKF','IKR','RB','RC','RE','CJE','CJC','TF','TR'},'PNP':{'IS','BF','BR','VAF','VAR','IKF','IKR','RB','RC','RE','CJE','CJC','TF','TR'},'NMOS':{'VTO','KP','GAMMA','PHI','LAMBDA','RD','RS','CGSO','CGDO'},'PMOS':{'VTO','KP','GAMMA','PHI','LAMBDA','RD','RS','CGSO','CGDO'}}
    for m in models:
        if set(m)!={'name','type','parameters'}:raise ValueError('Model fields: name, type, parameters')
        name=identifier(m['name']);kind=m['type'].upper();parameters=m['parameters']
        if name.upper() in defined or kind not in allowed or not isinstance(parameters,dict) or set(parameters)-allowed[kind]:raise ValueError('Invalid or duplicate model')
        defined[name.upper()]=kind
        fields=' '.join(k+'='+str(number(v,k,-1e12,1e12)) for k,v in parameters.items())
        lines.append(f'.model {name} {kind} ({fields})')
    counts={'R':2,'C':2,'L':2,'V':2,'I':2,'D':2,'Q':3,'M':4}
    for c in components:
        if set(c)-{'ref','nodes','value','model','pulse','width_m','length_m'}:raise ValueError('Unsupported component field')
        ref=identifier(c['ref']);kind=ref[0].upper()
        if ref.upper() in refs or kind not in counts:raise ValueError('Invalid/duplicate component reference')
        refs.add(ref.upper());ns=c['nodes']
        if not isinstance(ns,list) or len(ns)!=counts[kind]:raise ValueError('Wrong terminal count for '+ref)
        ns=[identifier(str(n)) for n in ns];nodes.update(ns);tail=''
        if kind in 'RCLVI':
            value=number(c.get('value',0),'value',1e-18 if kind in 'RCL' else -1e9,1e12);tail=str(value)
            if 'pulse' in c:
                if kind not in 'VI' or len(c['pulse'])!=7:raise ValueError('PULSE needs V/I plus [low,high,delay,rise,fall,width,period]')
                pulse=[number(x,'pulse',-1e9 if i<2 else 0,1e9) for i,x in enumerate(c['pulse'])]
                if pulse[3]<=0 or pulse[4]<=0 or pulse[6]<=0 or pulse[5]>pulse[6]:raise ValueError('PULSE times must be physically ordered with positive rise/fall/period')
                tail='PULSE('+ ' '.join(map(str,pulse))+')'
        else:
            model=identifier(c['model']);t=defined.get(model.upper())
            if t not in ({'D'} if kind=='D' else {'NPN','PNP'} if kind=='Q' else {'NMOS','PMOS'}):raise ValueError('Missing or wrong model for '+ref)
            tail=model
            if kind=='M':tail+=' W='+str(number(c.get('width_m',10e-6),'W',1e-9,1))+' L='+str(number(c.get('length_m',1e-6),'L',1e-9,1))
        lines.append(' '.join([ref,*ns,tail]))
    if '0' not in nodes:raise ValueError('Circuit requires reference ground node 0')
    lines.extend(['.options noacct','.end'])
    return '\n'.join(lines)+'\n',nodes

def simulate(p,context):
    keys(p,{'components','models','analysis','step_s','duration_s','outputs'})
    text,nodes=netlist(p);analysis=p.get('analysis','op')
    if analysis not in ('op','transient'):raise ValueError('analysis: op or transient')
    outputs=p.get('outputs',[x for x in sorted(nodes) if x!='0'][:8])
    if not isinstance(outputs,list) or not 1<=len(outputs)<=16 or not set(outputs)<=(nodes-{'0'}):raise ValueError('Outputs must name 1..16 non-ground circuit nodes')
    duration=number(p.get('duration_s',.01),'duration',1e-9,10);step=number(p.get('step_s',duration/1000),'step',duration/10000,duration/10)
    dll=context.root/'Tools/KiCad/bin/ngspice.dll'
    if not dll.is_file():raise RuntimeError('Install the bundled Windows KiCad/ngspice component first')
    result,contents=worker(context,'spice',{'dll':str(dll),'analysis':analysis,'duration':duration,'step':step,'outputs':outputs},{'circuit.cir':text.encode()},timeout=30)
    result['limitations']=['Model-based SPICE voltages, including diode/BJT/MOSFET and switching transients. Accuracy depends on supplied device parameters and valid topology.','Generic models do not replace manufacturer models, thermal/parasitic modeling, PCB DRC or physical measurement. External model files and SPICE command scripts are not executed.']
    contents['circuit.cir']=text;return result,contents

def board(p,context):
    keys(p,{'width_mm','height_mm','components','tracks'})
    width=number(p['width_mm'],'width',10,300);height=number(p['height_mm'],'height',10,300)
    components=p['components'];tracks=p.get('tracks',[])
    if not isinstance(components,list) or not 1<=len(components)<=128 or not isinstance(tracks,list) or len(tracks)>2000:raise ValueError('Board exceeds component/track limits')
    # Each pad names its actual pin function. No guessed transistor pinout.
    ns=set();refs=set();parts=[];bom=[]
    for c in components:
        if set(c)-{'ref','value','x_mm','y_mm','pads','datasheet'}:raise ValueError('Unknown board component field')
        ref=identifier(c['ref']);pads=c['pads']
        if ref.upper() in refs or not isinstance(pads,list) or not 2<=len(pads)<=40:raise ValueError('Duplicate ref or invalid pad count')
        refs.add(ref.upper());x=number(c['x_mm'],'x',1,width-1);y=number(c['y_mm'],'y',1,height-1);seen=set();normalized=[]
        for pad in pads:
            if set(pad)!={'number','net','function','dx_mm','dy_mm','diameter_mm','drill_mm'}:raise ValueError('Each pad needs number/net/function/dx_mm/dy_mm/diameter_mm/drill_mm')
            n=identifier(str(pad['number']));net=identifier(str(pad['net']));function=identifier(pad['function']);dx=number(pad['dx_mm'],'dx',-100,100);dy=number(pad['dy_mm'],'dy',-100,100);diam=number(pad['diameter_mm'],'pad diameter',.5,10);drill=number(pad['drill_mm'],'drill',.2,diam-.2)
            if n in seen or not 0<x+dx<width or not 0<y+dy<height:raise ValueError('Duplicate pad or pad outside board')
            seen.add(n);ns.add(net);normalized.append((n,net,function,dx,dy,diam,drill))
        if ref[0].upper() in ('Q','M') and not c.get('datasheet'):raise ValueError('Transistor board pads require a datasheet reference and explicit pin functions')
        parts.append((c,ref,x,y,normalized));bom.append({'ref':ref,'value':str(c.get('value','')),'datasheet':str(c.get('datasheet','')),'pins':[{k:pad[k] for k in ('number','net','function')} for pad in pads]})
    ids={n:i+1 for i,n in enumerate(sorted(ns))};quote=lambda x:json.dumps(str(x),ensure_ascii=True)
    lines=['(kicad_pcb (version 20241229) (generator "PortalAI") (general (thickness 1.6)) (paper "A4")','(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (5 "F.SilkS" user) (7 "B.SilkS" user) (1 "F.Mask" user) (3 "B.Mask" user) (25 "Edge.Cuts" user) (31 "F.CrtYd" user) (29 "B.CrtYd" user) (35 "F.Fab" user) (33 "B.Fab" user))','(setup (pad_to_mask_clearance 0))']
    lines+=['(net '+str(i)+' '+quote(n)+')' for n,i in ids.items()]
    for c,ref,x,y,pads in parts:
        lines.append(f'(footprint "PortalAI:Explicit_THT" (layer "F.Cu") (at {x} {y}) (attr through_hole) (property "Reference" {quote(ref)} (at 0 -3) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))')
        # The property is closed; the enclosing footprint remains open for its pads.
        for n,net,fun,dx,dy,diam,drill in pads:lines.append(f'(pad {quote(n)} thru_hole circle (at {dx} {dy}) (size {diam} {diam}) (drill {drill}) (layers "*.Cu" "*.Mask") (net {ids[net]} {quote(net)}) (pinfunction {quote(fun)}))')
        lines.append(')')
    for t in tracks:
        if set(t)!={'net','start_mm','end_mm','width_mm','layer'}:raise ValueError('Track fields: net,start_mm,end_mm,width_mm,layer')
        if t['net'] not in ids or t['layer'] not in ('F.Cu','B.Cu'):raise ValueError('Invalid track net/layer')
        a=t['start_mm'];b=t['end_mm']
        if len(a)!=2 or len(b)!=2:raise ValueError('Track coordinates need x,y')
        a=[number(a[0],'track x',0,width),number(a[1],'track y',0,height)];b=[number(b[0],'track x',0,width),number(b[1],'track y',0,height)]
        w=number(t['width_mm'],'track width',.1,5);lines.append(f'(segment (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (width {w}) (layer {quote(t["layer"])}) (net {ids[t["net"]]}))')
    lines.append(f'(gr_rect (start 0 0) (end {width} {height}) (stroke (width 0.05) (type default)) (fill none) (layer "Edge.Cuts"))');lines.append(')')
    return {'components':len(parts),'tracks':len(tracks),'board_mm':[width,height],'manufacturing_ready':False,'limitations':['Editable KiCad board with explicit pad/net mapping and optional supplied copper segments; no automatic placement/routing or fabricated transistor pinout.','Run KiCad DRC, verify datasheets/footprints, clearances and current capacity, and finish unrouted nets before fabrication.']},{'board.kicad_pcb':'\n'.join(lines),'bom.json':json.dumps(bom,indent=2)}
