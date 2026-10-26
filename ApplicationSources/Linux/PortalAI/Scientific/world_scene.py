"""Bounded, offline teaching physics; never an engineering safety certificate."""
import copy
import json
import math
import re
from pathlib import Path
from Scientific.extensions_common import asset

STEP = 1 / 120
LIMITATIONS = [
    'Discrete rigid collisions can tunnel. Breakage is pre-cut boxes or force-threshold connections, not stress/FEA or blast-damage prediction.',
    'Liquid zones use approximate displaced volume; separate SPH particles are a small weakly-compressible demonstration, not calibrated CFD.',
    'Heat is a lumped-capacity energy model. Fire consumes a declared energy budget; no combustion chemistry, oxygen, phase changes or smoke toxicity.',
    'Ropes are segmented, tension-only links; pulleys have ideal fixed massless frictionless supports. Wire bending and plasticity are not modeled.',
    'Save setup retains rigid states and active connections; it restarts fluid/rope internal motion and visual effects, never replays a burst.',
]

def schema():
    return json.loads(Path(__file__).with_name('world_schema.json').read_text(encoding='utf-8'))

def validate(p):
    spec=schema()
    def walk(v,s,path):
        if '$ref' in s:s=spec['$defs'][s['$ref'].split('/')[-1]]
        t=s['type']
        if t=='object':
            if not isinstance(v,dict) or set(v)-set(s['properties']):raise ValueError(path+': unknown fields or not an object')
            return {k:walk(v.get(k,copy.deepcopy(q['default'])),q,path+'.'+k) for k,q in s['properties'].items()}
        if t=='array':
            if not isinstance(v,list) or not s.get('minItems',0)<=len(v)<=s['maxItems']:raise ValueError(path+': array size out of bounds')
            return [walk(x,s['items'],path+'[]') for x in v]
        if t in ('number','integer'):
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not s['minimum']<=v<=s['maximum'] or (t=='integer' and int(v)!=v):raise ValueError(path+': number out of bounds')
        elif not isinstance(v,str) or len(v)>s.get('maxLength',1000) or ('pattern' in s and not re.fullmatch(s['pattern'],v)) or ('enum' in s and v not in s['enum']):raise ValueError(path+': invalid string')
        return v
    p=copy.deepcopy(p)
    if not isinstance(p,dict):raise ValueError('Scene must be an object')
    for key in ('objects','connections'):
        for i,row in enumerate(p.get(key,[]) if isinstance(p.get(key,[]),list) else []):
            if isinstance(row,dict):row.setdefault('id',('body' if key=='objects' else 'link')+str(i))
    s=walk(p,spec,'scene');bodies={o['id']:o for o in s['objects']}
    if len(bodies)!=len(s['objects']):raise ValueError('Duplicate body ID')
    if len({c['id'] for c in s['connections']})!=len(s['connections']):raise ValueError('Duplicate connection ID')
    reserve=len(bodies)
    for o in bodies.values():
        if o['shape']=='sphere' and len(set(o['size']))!=1:raise ValueError('Sphere diameters must match')
        if o['break_speed']:
            if o['shape']!='box' or min(o['size'])<.2 or o['mass']<.008 or o['heat_capacity']<.008:raise ValueError('Breakage needs a dynamic box, size >= .2 and mass/heat capacity >= .008')
            reserve+=7
    if reserve>96:raise ValueError('Bodies plus reserved fragments exceed 96')
    rope_nodes=0
    for c in s['connections']:
        if c['a'] not in bodies or c['b'] not in bodies or c['a']==c['b']:raise ValueError('Connection must reference two distinct existing body IDs')
        a,b=bodies[c['a']],bodies[c['b']];inv=sum(1/o['mass'] for o in (a,b) if o['mass'])
        if not inv:raise ValueError('Connection needs a dynamic body')
        if c['kind']=='spring' and (STEP*math.sqrt(c['stiffness']*inv)>.4 or STEP*c['damping']*inv>.4):raise ValueError('Spring too stiff/damped for mass and fixed step; increase mass or reduce stiffness/damping')
        if c['kind']=='rope':
            rope_nodes+=c['segments']-1
            if math.dist(a['position'],b['position'])>c['length']+max(.01,c['length']*.01):raise ValueError('Rope length shorter than endpoint separation')
        if c['kind']=='pulley':
            used=math.dist(a['position'],c['anchor_a'])+c['ratio']*math.dist(b['position'],c['anchor_b'])
            if used>c['length']+max(.01,c['length']*.01):raise ValueError('Pulley length shorter than weighted hanging lengths')
    if rope_nodes>128:raise ValueError('At most 128 rope nodes')
    particles=0
    for f in s['fluids']:
        particles+=math.prod(f['counts'])
        if any(f[k]!=s['fluids'][0][k] for k in ('spacing','density','viscosity','sound_speed')):raise ValueError('SPH groups share one fluid: spacing, density, viscosity and sound speed must match')
        if STEP*f['sound_speed']>.2*2*f['spacing']:raise ValueError('SPH sound speed exceeds fixed-step stability bound')
    if particles>256:raise ValueError('At most 256 physical fluid particles')
    if s['liquids'] and (s['gravity'][0]!=0 or s['gravity'][2]!=0 or s['gravity'][1]>=0):raise ValueError('Buoyancy zones require downward Y gravity')
    for i,a in enumerate(s['liquids']):
        for b in s['liquids'][:i]:
            if all(abs(a['position'][k]-b['position'][k])<(a['size'][k]+b['size'][k])/2 for k in range(3)):raise ValueError('Liquid zones must not overlap')
        for f in s['fluids']:
            if all(abs(a['position'][k]-f['position'][k])<a['size'][k]/2+f['counts'][k]*f['spacing']/2 for k in range(3)):raise ValueError('Use bulk buoyancy or SPH in one region, not both')
    return s

def describe():
    examples=json.loads(Path(__file__).with_name('world_examples.json').read_text(encoding='utf-8'))
    return {'schema':schema(),'examples':examples,'fixed_step_seconds':STEP,'limits':{'bodies_including_fragments':96,'rope_nodes':128,'fluid_particles':256,'visual_particles':256},'limitations':LIMITATIONS}

def run(p,context):
    scene=validate({k:v for k,v in p.items() if k not in ('export','output_dir')});base=context.root/'Scientific'
    replacements={'__THREE__':asset(context,'Scientific/vendor/three.cjs').read_text(encoding='utf-8'),'__CANNON__':asset(context,'Scientific/vendor/cannon-es.cjs').read_text(encoding='utf-8'),'__PHYSICS__':(base/'world_physics.js').read_text(encoding='utf-8'),'__UI__':(base/'world_ui.js').read_text(encoding='utf-8'),'__SCHEMA__':json.dumps(schema(),ensure_ascii=True),'__EXAMPLES__':json.dumps(describe()['examples'],ensure_ascii=True),'__SCENE__':json.dumps(scene,ensure_ascii=True,allow_nan=False)}
    document=(base/'world_scene.html').read_text(encoding='utf-8')
    # One-pass expansion: data cannot introduce a second template substitution.
    document=re.sub('|'.join(re.escape(k) for k in replacements),lambda m:re.sub('</script',r'<\\/script',replacements[m[0]],flags=re.I),document)
    return {'objects':len(scene['objects']),'engine':'cannon-es 0.20.0 + Three.js 0.160.1','renderer':'WebGL; physics CPU','network_required':False,'limits':describe()['limits'],'fixed_step_seconds':STEP,'features':['wind and drag','springs, tension ropes, ideal pulleys, breakable welds','buoyancy zones and bounded SPH liquid particles','lumped heat exchange and finite-fuel fire','radial impulse bursts and pre-cut box breakage','visual smoke, fire and spark particles','offline controls, presets and validated save/load'],'limitations':LIMITATIONS},{'world.html':document,'scene.json':json.dumps(scene,indent=2)}
