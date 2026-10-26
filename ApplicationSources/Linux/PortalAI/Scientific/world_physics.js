/* First-party bounded physics harness. SI units; temperature in Celsius.
 * Cannon-es supplies rigid contacts, constraints, springs and SPH. */
'use strict';
function portalPhysics(C, schema) {
  const STEP=1/120, V=a=>new C.Vec3(...a), clone=x=>JSON.parse(JSON.stringify(x));
  const distance=(a,b)=>Math.hypot(...a.map((x,i)=>x-b[i]));
  function validate(input) {
    function walk(v,s,path) {
      if(s.$ref)s=schema.$defs[s.$ref.split('/').pop()];
      if(s.type==='object') {
        if(!v||typeof v!=='object'||Array.isArray(v)||Object.keys(v).some(k=>!Object.hasOwn(s.properties,k)))throw Error(path+': unknown fields or not an object');
        return Object.fromEntries(Object.entries(s.properties).map(([k,q])=>[k,walk(Object.hasOwn(v,k)?v[k]:clone(q.default),q,path+'.'+k)]));
      }
      if(s.type==='array') {
        if(!Array.isArray(v)||v.length<(s.minItems||0)||v.length>s.maxItems)throw Error(path+': array size out of bounds');
        return v.map(x=>walk(x,s.items,path+'[]'));
      }
      if(s.type==='number'||s.type==='integer') {
        if(typeof v!=='number'||!Number.isFinite(v)||v<s.minimum||v>s.maximum||(s.type==='integer'&&!Number.isInteger(v)))throw Error(path+': number out of bounds');
      } else if(typeof v!=='string'||v.length>(s.maxLength||1000)||(s.pattern&&new RegExp(s.pattern).exec(v)?.[0]!==v)||(s.enum&&!s.enum.includes(v)))throw Error(path+': invalid string');
      return v;
    }
    // Do not stringify first: JSON would turn nonfinite values into null.
    if(!input||typeof input!=='object'||Array.isArray(input))throw Error('Scene must be an object');
    const raw={...input};
    for(const key of ['objects','connections'])if(Array.isArray(raw[key]))raw[key]=raw[key].map((x,i)=>x&&typeof x==='object'?{id:(key==='objects'?'body':'link')+i,...x}:x);
    const s=walk(raw,schema,'scene'), map=new Map(s.objects.map(o=>[o.id,o]));
    if(map.size!==s.objects.length)throw Error('Duplicate body ID');
    if(new Set(s.connections.map(c=>c.id)).size!==s.connections.length)throw Error('Duplicate connection ID');
    let reserve=s.objects.length,nodes=0;
    for(const o of s.objects) {
      if(o.shape==='sphere'&&!o.size.every(x=>x===o.size[0]))throw Error('Sphere diameters must match');
      if(o.break_speed) {
        if(o.shape!=='box'||Math.min(...o.size)<.2||o.mass<.008||o.heat_capacity<.008)throw Error('Breakage needs a dynamic box, size >= .2 and mass/heat capacity >= .008');
        reserve+=7;
      }
    }
    if(reserve>96)throw Error('Bodies plus reserved fragments exceed 96');
    for(const c of s.connections) {
      const a=map.get(c.a),b=map.get(c.b);
      if(!a||!b||a===b)throw Error('Connection must reference two distinct existing body IDs');
      const inv=(a.mass?1/a.mass:0)+(b.mass?1/b.mass:0);
      if(!inv)throw Error('Connection needs a dynamic body');
      if(c.kind==='spring'&&(STEP*Math.sqrt(c.stiffness*inv)>.4||STEP*c.damping*inv>.4))throw Error('Spring too stiff/damped for mass and fixed step; increase mass or reduce stiffness/damping');
      if(c.kind==='rope') {
        nodes+=c.segments-1;
        if(distance(a.position,b.position)>c.length+Math.max(.01,c.length*.01))throw Error('Rope length shorter than endpoint separation');
      }
      if(c.kind==='pulley'&&distance(a.position,c.anchor_a)+c.ratio*distance(b.position,c.anchor_b)>c.length+Math.max(.01,c.length*.01))throw Error('Pulley length shorter than weighted hanging lengths');
    }
    if(nodes>128)throw Error('At most 128 rope nodes');
    let particles=0;
    for(const f of s.fluids) {
      particles+=f.counts.reduce((a,b)=>a*b,1);
      if(['spacing','density','viscosity','sound_speed'].some(k=>f[k]!==s.fluids[0][k]))throw Error('SPH groups share one fluid: spacing, density, viscosity and sound speed must match');
      if(STEP*f.sound_speed>.4*f.spacing)throw Error('SPH sound speed exceeds fixed-step stability bound');
    }
    if(particles>256)throw Error('At most 256 physical fluid particles');
    if(s.liquids.length&&(s.gravity[0]!==0||s.gravity[2]!==0||s.gravity[1]>=0))throw Error('Buoyancy zones require downward Y gravity');
    for(let i=0;i<s.liquids.length;i++) {
      const a=s.liquids[i];
      for(const b of s.liquids.slice(0,i))if(a.position.every((x,k)=>Math.abs(x-b.position[k])<(a.size[k]+b.size[k])/2))throw Error('Liquid zones must not overlap');
      for(const f of s.fluids)if(a.position.every((x,k)=>Math.abs(x-f.position[k])<a.size[k]/2+f.counts[k]*f.spacing/2))throw Error('Use bulk buoyancy or SPH in one region, not both');
    }
    return s;
  }

  // Ideal pulley: |A-anchorA| + ratio*|B-anchorB| <= length.
  // The negative multiplier is rope tension. Squared Jacobian weights are
  // essential for the effective inverse mass when ratio != 1.
  class PulleyEquation extends C.Equation {
    constructor(a,b,data){super(a,b,-1e7,0);this.data=data;this.gap=0;}
    computeB(h) {
      const d=this.data,ga=this.jacobianElementA.spatial,gb=this.jacobianElementB.spatial;
      this.bi.position.vsub(V(d.anchor_a),ga);this.bj.position.vsub(V(d.anchor_b),gb);
      const la=ga.length(),lb=gb.length();ga.scale(1/Math.max(la,1e-9),ga);gb.scale(d.ratio/Math.max(lb,1e-9),gb);
      this.gap=la+d.ratio*lb-d.length;
      return -this.gap*this.a-this.computeGW()*this.b-h*this.computeGiMf();
    }
    computeGiMGt(){return this.bi.invMassSolve*this.jacobianElementA.spatial.lengthSquared()+this.bj.invMassSolve*this.jacobianElementB.spatial.lengthSquared();}
  }
  class Pulley extends C.Constraint {
    constructor(a,b,data){super(a,b,{collideConnected:true});this.equations=[new PulleyEquation(a,b,data)];}
    update(){}
  }

  class Lab {
    constructor(input) {
      this.config=validate(input);this.time=0;this.bodies=new Map();this.links=[];this.fluids=[];this.effects=[];this.events=[];this.fractures=new Set();this.serial=0;this.seed=12345;this.emitterAcc=new WeakMap();
      this.energy={heater_j:0,fuel_j:0,ignition_j:0};this.broken=0;
      this.world=new C.World({gravity:V(this.config.gravity),allowSleep:false});
      this.world.broadphase=new C.SAPBroadphase(this.world);this.world.solver.iterations=80;
      this.material=new C.Material('lab');
      this.world.addContactMaterial(new C.ContactMaterial(this.material,this.material,{friction:this.config.friction,restitution:this.config.restitution}));
      const ground=new C.Body({mass:0,shape:new C.Plane(),material:this.material,collisionFilterGroup:1,collisionFilterMask:7});
      ground.quaternion.setFromEuler(-Math.PI/2,0,0);this.world.addBody(ground);
      for(const o of this.config.objects)this.addBody(o);
      for(const c of this.config.connections)this.addLink(c);
      for(const f of this.config.fluids)this.addFluid(f);
    }
    random(){this.seed=(1664525*this.seed+1013904223)>>>0;return this.seed/4294967296;}
    unique(prefix='body'){let id;do{id=prefix+(++this.serial);}while(this.bodies.has(id)||this.links.some(x=>x.data.id===id));return id;}
    addBody(data) {
      const d=clone(data),shape=d.shape==='box'?new C.Box(V(d.size.map(x=>x/2))):new C.Sphere(d.size[0]/2);
      const body=new C.Body({mass:d.mass,shape,material:this.material,position:V(d.position),linearDamping:0,angularDamping:0,collisionFilterGroup:1,collisionFilterMask:7});
      body.quaternion.setFromEuler(...d.rotation,'XYZ');body.velocity.copy(V(d.velocity));body.angularVelocity.copy(V(d.angular_velocity));
      const e={data:d,body,temperature:d.temperature,fuel:d.fuel_j,burning:false};
      body.addEventListener('collide',event=>{if(d.break_speed&&Math.abs(event.contact.getImpactVelocityAlongNormal())>=d.break_speed)this.fractures.add(d.id);});
      this.world.addBody(body);this.bodies.set(d.id,e);return e;
    }
    removeBody(id) {
      const e=this.bodies.get(id);if(!e)return;
      for(const l of this.links)if(!l.broken&&(l.data.a===id||l.data.b===id))this.breakLink(l);
      this.world.removeBody(e.body);this.bodies.delete(id);
    }
    addLink(data) {
      if(this.links.length>=48||this.links.reduce((n,l)=>n+l.nodes.length,0)+(data.kind==='rope'?data.segments-1:0)>128)throw Error('Runtime connection capacity reached; save/reset the setup to clear released rope nodes');
      const d=clone(data),a=this.bodies.get(d.a).body,b=this.bodies.get(d.b).body,l={data:d,nodes:[],constraints:[],broken:false,force:0};
      if(d.kind==='spring')l.spring=new C.Spring(a,b,{restLength:d.length,stiffness:d.stiffness,damping:d.damping});
      if(l.spring)l.spring.damping=d.damping; // Cannon's constructor treats 0 as a missing value.
      if(d.kind==='weld')l.constraints.push(new C.LockConstraint(a,b,{maxForce:1e7}));
      if(d.kind==='pulley')l.constraints.push(new Pulley(a,b,d));
      if(d.kind==='rope') {
        const start=a.position,end=b.position,delta=end.vsub(start),straight=delta.length();
        // Sag in a perpendicular plane. Binary-search its arc length so the
        // initial chain never starts artificially stretched.
        let sag=new C.Vec3(0,-1,0),axis=delta.unit();
        if(Math.abs(axis.dot(sag))>.95)sag=new C.Vec3(1,0,0);
        axis.scale(axis.dot(sag),axis);sag.vsub(axis,sag);sag.normalize();
        const point=(i,depth)=>{const t=i/d.segments;return start.vadd(delta.scale(t)).vadd(sag.scale(Math.sin(Math.PI*t)*depth));};
        let low=0,high=d.length;
        for(let n=0;n<30;n++){const mid=(low+high)/2;let len=0;for(let i=1;i<=d.segments;i++)len+=point(i,mid).distanceTo(point(i-1,mid));if(len>d.length)high=mid;else low=mid;}
        const chain=[a];
        for(let i=1;i<d.segments;i++) {
          const node=new C.Body({mass:d.mass/(d.segments-1),shape:new C.Sphere(.035),position:point(i,straight<d.length?low:0),material:this.material,linearDamping:0,collisionFilterGroup:4,collisionFilterMask:1});
          this.world.addBody(node);l.nodes.push(node);chain.push(node);
        }
        chain.push(b);l.chain=chain;
        // Each rest length follows the initialized arc; slack cannot push.
        for(let i=1;i<chain.length;i++){const c=new C.DistanceConstraint(chain[i-1],chain[i],chain[i].position.distanceTo(chain[i-1].position)*Math.min(1,d.length/Math.max(straight,1e-9)),1e7);c.collideConnected=false;c.distanceEquation.maxForce=0;l.constraints.push(c);}
      }
      for(const c of l.constraints){for(const q of c.equations)q.setSpookParams(1e7,4,STEP);this.world.addConstraint(c);}
      this.links.push(l);return l;
    }
    breakLink(l) {
      if(l.broken)return;l.broken=true;this.broken++;
      for(const c of l.constraints)this.world.removeConstraint(c);
      // Released rope mass remains as free nodes until an explicit reset.
      this.events.push('Connection '+l.data.id+' released');if(this.events.length>8)this.events.shift();
    }
    addFluid(data) {
      const d=clone(data),sph=this.fluids.length?this.fluids[0].sph:new C.SPHSystem();sph.density=d.density;sph.smoothingRadius=2*d.spacing;sph.speedOfSound=d.sound_speed;sph.viscosity=d.viscosity;
      const f={data:d,sph,particles:[]};
      for(let x=0;x<d.counts[0];x++)for(let y=0;y<d.counts[1];y++)for(let z=0;z<d.counts[2];z++) {
        const pos=[x,y,z].map((k,i)=>d.position[i]+(k-(d.counts[i]-1)/2)*d.spacing);
        const b=new C.Body({mass:d.density*d.spacing**3,shape:new C.Sphere(.22*d.spacing),position:V(pos),material:this.material,linearDamping:0,collisionFilterGroup:2,collisionFilterMask:1});
        this.world.addBody(b);sph.add(b);f.particles.push(b);
      }
      this.fluids.push(f);
    }
    volume(e){return e.data.shape==='sphere'?Math.PI*e.data.size[0]**3/6:e.data.size.reduce((a,b)=>a*b,1);}
    submerged(e,z) {
      const b=e.body;b.updateAABB();const lo=b.aabb.lowerBound.toArray(),hi=b.aabb.upperBound.toArray();
      const overlap=z.position.map((x,i)=>Math.max(0,Math.min(hi[i],x+z.size[i]/2)-Math.max(lo[i],x-z.size[i]/2)));
      return this.volume(e)*overlap.reduce((p,x,i)=>p*x/Math.max(hi[i]-lo[i],1e-9),1);
    }
    drag(b,target,rate) {if(!b.mass)return;const factor=1-Math.exp(-rate*STEP);b.velocity.vadd(V(target).vsub(b.velocity).scale(factor),b.velocity);}
    exchange(a,b,k) {
      if(!k)return;const ca=a.data.heat_capacity,cb=b.data.heat_capacity;
      const q=(a.temperature-b.temperature)/(1/ca+1/cb)*(-Math.expm1(-k*(1/ca+1/cb)*STEP));
      a.temperature-=q/ca;b.temperature+=q/cb;
    }
    distributeHeat(position,radius,joules,exclude) {
      const rows=[...this.bodies.values()].filter(e=>e!==exclude).map(e=>[e,Math.max(0,1-e.body.position.distanceTo(position)/radius)]).filter(x=>x[1]>0);
      const sum=rows.reduce((a,x)=>a+x[1],0);if(!sum)return;
      for(const [e,w] of rows)e.temperature+=joules*w/sum/e.data.heat_capacity;
    }
    ignite(id) {
      const e=this.bodies.get(id);if(!e||!e.fuel||!e.data.burn_w)throw Error('Select a body with fuel energy and burn power');
      this.energy.ignition_j+=Math.max(0,e.data.ignition_c-e.temperature)*e.data.heat_capacity;
      e.temperature=Math.max(e.temperature,e.data.ignition_c);e.burning=true;
    }
    burst(position,radius,impulse) {
      if(!Array.isArray(position)||position.length!==3||!position.every(x=>Number.isFinite(x)&&Math.abs(x)<=100)||!Number.isFinite(radius)||radius<.1||radius>20||!Number.isFinite(impulse)||impulse<0||impulse>1000)throw Error('Burst needs a bounded center, radius .1..20 and impulse 0..1000 N·s');
      const p=V(position),rows=[...this.bodies.values()].filter(e=>e.body.mass).map(e=>[e,Math.max(0,1-e.body.position.distanceTo(p)/radius)]).filter(x=>x[1]>0),sum=rows.reduce((a,x)=>a+x[1],0);
      for(const [e,w] of rows){let dir=e.body.position.vsub(p);if(dir.length()<1e-9)dir=new C.Vec3(0,1,0);dir.normalize();e.body.applyImpulse(dir.scale(impulse*w/sum));}
      for(let i=0;i<80;i++)this.particle(p,'sparks',V([(this.random()-.5)*8,this.random()*8,(this.random()-.5)*8]),1.5);
      return {affected:rows.length,scalar_impulse_ns:sum?impulse:0};
    }
    particle(position,kind,velocity,lifetime) {
      if(this.effects.length>=256)return;
      this.effects.push({position:position.clone(),velocity:velocity.clone(),kind,life:lifetime,total:lifetime});
    }
    fracture(id) {
      const e=this.bodies.get(id);if(!e||!e.data.break_speed)return;
      const b=e.body,d=e.data,angles=new C.Vec3();b.quaternion.toEuler(angles);this.removeBody(id);
      for(const x of [-1,1])for(const y of [-1,1])for(const z of [-1,1]) {
        const offset=b.quaternion.vmult(V([x,y,z].map((n,i)=>n*d.size[i]/4)));
        const v=b.angularVelocity.cross(offset).vadd(b.velocity);
        this.addBody({...d,id:this.unique('fragment'),name:d.name.slice(0,65)+' fragment',mass:d.mass/8,size:d.size.map(n=>n/2),position:b.position.vadd(offset).toArray(),rotation:angles.toArray(),velocity:v.toArray(),angular_velocity:b.angularVelocity.toArray(),heat_capacity:d.heat_capacity/8,temperature:e.temperature,fuel_j:e.fuel/8,burn_w:d.burn_w/8,convection:d.convection/8,break_speed:0});
      }
      this.events.push('Pre-cut fracture: '+d.name);if(this.events.length>8)this.events.shift();
    }
    step() {
      for(const e of this.bodies.values()) {
        const b=e.body,d=e.data,relative=V(this.config.wind).vsub(b.velocity),speed=relative.length();
        if(b.mass&&speed) {
          const area=Math.max(d.size[0]*d.size[1],d.size[0]*d.size[2],d.size[1]*d.size[2]);
          const k=.5*this.config.air_density*d.drag_coefficient*area/b.mass;
          b.velocity.vadd(relative.scale(k*speed*STEP/(1+k*speed*STEP)),b.velocity);
        }
        e.temperature+=(this.config.ambient_c-e.temperature)*(-Math.expm1(-d.convection*STEP/d.heat_capacity));
        for(const z of this.config.liquids) {
          const displaced=this.submerged(e,z),fraction=displaced/this.volume(e);
          if(!fraction)continue;
          if(b.mass)b.applyForce(new C.Vec3(0,-this.config.gravity[1]*z.density*displaced,0));
          this.drag(b,z.flow,z.drag*fraction);
          e.temperature+=(z.temperature-e.temperature)*(-Math.expm1(-z.heat_transfer*fraction*STEP/d.heat_capacity));
        }
        e.burning=e.fuel>0&&d.burn_w>0&&e.temperature>=d.ignition_c;
        if(e.burning) {
          const energy=Math.min(e.fuel,d.burn_w*STEP);e.fuel-=energy;this.energy.fuel_j+=energy;
          e.temperature+=energy*.5/d.heat_capacity;this.distributeHeat(b.position,3,energy*.5,e);
          if(this.random()<STEP*35)this.particle(b.position,'fire',V([(this.random()-.5)*.5,1.5,(this.random()-.5)*.5]),1.3);
          if(this.random()<STEP*12)this.particle(b.position,'smoke',V([0,1,0]),3);
        }
      }
      for(const h of this.config.heaters){this.energy.heater_j+=h.power_w*STEP;this.distributeHeat(V(h.position),h.radius,h.power_w*STEP);}
      for(const l of this.links)if(!l.broken) {
        const a=this.bodies.get(l.data.a),b=this.bodies.get(l.data.b);this.exchange(a,b,l.data.conductance);
        if(l.spring) {
          const delta=b.body.position.vsub(a.body.position),len=delta.length(),normal=len?delta.scale(1/len):new C.Vec3();
          l.force=Math.abs(l.data.stiffness*(len-l.data.length)+l.data.damping*b.body.velocity.vsub(a.body.velocity).dot(normal));
          if(l.data.break_force&&l.force>l.data.break_force)this.breakLink(l);else l.spring.applyForce();
        }
      }
      for(const f of this.fluids) {
        // Stop rather than altering the fixed step or requested parameters.
        if(f.particles.some(b=>STEP*(f.data.sound_speed+b.velocity.length())>.4*f.data.spacing))throw Error('Fluid speed exceeded fixed-step stability bound; reset with gentler forces or larger spacing');

      }
      for(const sph of new Set(this.fluids.map(f=>f.sph)))sph.update();
      this.world.step(STEP);this.time+=STEP;
      for(const l of this.links)if(!l.broken&&l.constraints.length) {
        let force=0,torque=0;
        for(const c of l.constraints)c.equations.forEach((e,i)=>{if(l.data.kind==='weld'&&i>=3)torque=Math.max(torque,Math.abs(e.multiplier));else force=Math.max(force,Math.abs(e.multiplier));});
        l.force=force;if((l.data.break_force&&force>l.data.break_force)||(l.data.break_torque&&torque>l.data.break_torque))this.breakLink(l);
      }
      for(const id of this.fractures)this.fracture(id);this.fractures.clear();
      for(const m of this.config.emitters) {
        let amount=(this.emitterAcc.get(m)||0)+m.rate*STEP;
        while(amount>=1){amount--;this.particle(V(m.position),m.kind,V(m.velocity).vadd(V([(this.random()-.5)*.7,0,(this.random()-.5)*.7])),m.lifetime);}
        this.emitterAcc.set(m,amount);
      }
      this.effects=this.effects.filter(p=>{p.life-=STEP;if(p.life<=0)return false;p.velocity.y+=(p.kind==='sparks'?-9.81:.5)*STEP;p.velocity.x+=(this.config.wind[0]-p.velocity.x)*STEP*.3;p.velocity.z+=(this.config.wind[2]-p.velocity.z)*STEP*.3;p.position.vadd(p.velocity.scale(STEP),p.position);return true;});
      for(const b of this.world.bodies)if(!b.position.toArray().concat(b.velocity.toArray(),b.angularVelocity.toArray()).every(Number.isFinite)||b.position.length()>250||b.velocity.length()>200)throw Error('Simulation left its finite speed/position bounds; paused');
      for(const e of this.bodies.values())if(!Number.isFinite(e.temperature)||e.temperature>2000||e.temperature< -100)throw Error('Temperature outside supported -100..2000 C range; paused');
    }
    snapshot() {
      const objects=[...this.bodies.values()].map(e=>{const angles=new C.Vec3();e.body.quaternion.toEuler(angles);return {...e.data,position:e.body.position.toArray(),rotation:angles.toArray(),velocity:e.body.velocity.toArray(),angular_velocity:e.body.angularVelocity.toArray(),temperature:e.temperature,fuel_j:e.fuel};});
      const connections=this.links.filter(l=>!l.broken).map(l=>clone(l.data));
      // Remove internal emitter timing; saved files remain pure scene schema.
      const emitters=this.config.emitters.map(({_acc,...d})=>d);
      return validate({...this.config,objects,connections,emitters});
    }
  }
  return {Lab,validate,STEP,PulleyEquation};
}
if(typeof module!=='undefined'&&module.exports)module.exports=portalPhysics;
