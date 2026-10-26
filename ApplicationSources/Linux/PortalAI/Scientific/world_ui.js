'use strict';
try {
const P=portalPhysics(CANNON,LAB_SCHEMA),$=id=>document.getElementById(id),values=p=>['x','y','z'].map(k=>Number($(p+k).value));
let lab,baseline=LAB_INITIAL,running=true,accum=0,last=0,yaw=.65,pitch=.5,distance=25,drag=null,frames=0,average=16,quality=Math.min(devicePixelRatio||1,2),failed=false;
const meshes=new Map(),lines=new Map(),zones=[],fluidMeshes=[];
const message=t=>{$('message').textContent=t;};
const guard=fn=>()=>{try{fn();}catch(e){message(e.message);}};
const selected=()=>{const e=lab.bodies.get($('selection').value);if(!e)throw Error('Select an object');return e;};
const renderer=new THREE.WebGLRenderer({canvas:$('canvas'),antialias:true});renderer.setClearColor(0x152329);
const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(48,1,.1,400);scene.fog=new THREE.Fog(0x152329,80,180);
scene.add(new THREE.HemisphereLight(0xffffff,0x40505b,2.5));const light=new THREE.DirectionalLight(0xffffff,2.5);light.position.set(6,15,8);scene.add(light);scene.add(new THREE.GridHelper(40,40,0x82b7bc,0x334d59));
const floor=new THREE.Mesh(new THREE.PlaneGeometry(200,200),new THREE.MeshStandardMaterial({color:0x263942,roughness:.9}));floor.rotation.x=-Math.PI/2;floor.position.y=-.02;scene.add(floor);
const effectPositions=new Float32Array(256*3),effectColors=new Float32Array(256*3),effectGeometry=new THREE.BufferGeometry();
effectGeometry.setAttribute('position',new THREE.BufferAttribute(effectPositions,3));effectGeometry.setAttribute('color',new THREE.BufferAttribute(effectColors,3));
const effectPoints=new THREE.Points(effectGeometry,new THREE.PointsMaterial({size:.13,vertexColors:true,transparent:true,opacity:.8,depthWrite:false}));scene.add(effectPoints);
const ropePositions=new Float32Array(128*3),ropeGeometry=new THREE.BufferGeometry();ropeGeometry.setAttribute('position',new THREE.BufferAttribute(ropePositions,3));
const ropePoints=new THREE.Points(ropeGeometry,new THREE.PointsMaterial({size:.07,color:0xc6b58c}));ropePoints.frustumCulled=false;scene.add(ropePoints);
function dispose(o){scene.remove(o);o.geometry.dispose();o.material.dispose();}
function resize(){const v=$('view');renderer.setPixelRatio(quality);renderer.setSize(v.clientWidth,v.clientHeight,false);camera.aspect=v.clientWidth/Math.max(v.clientHeight,1);camera.updateProjectionMatrix();}
function controls(){for(const id of ['selection','other']){const old=$(id).value;$(id).replaceChildren();for(const [key,e] of lab.bodies){const o=document.createElement('option');o.value=key;o.textContent=e.data.name+' ('+key+')';$(id).append(o);}if(lab.bodies.has(old))$(id).value=old;}refreshDetails();}
function refreshDetails(){const e=lab.bodies.get($('selection').value);$('details').textContent=e?e.temperature.toFixed(1)+' °C · '+e.fuel.toFixed(0)+' J fuel\n'+e.body.velocity.length().toFixed(2)+' m/s · '+(e.burning?'burning':'not burning'):'';}
function populate(){const e=lab.bodies.get($('selection').value);if(!e)return;['x','y','z'].forEach((k,i)=>{$('p'+k).value=e.body.position.toArray()[i].toFixed(3);$('s'+k).value=e.data.size[i];});$('shape').value=e.data.shape;$('mass').value=e.data.mass;$('color').value=e.data.color;$('temperature').value=e.temperature.toFixed(2);$('capacity').value=e.data.heat_capacity;$('fuel').value=e.fuel.toFixed(2);$('burn').value=e.data.burn_w;$('breakspeed').value=e.data.break_speed;}
function reset(input){
  const next=new P.Lab(input); // Validate before replacing the working world.
  for(const o of meshes.values())dispose(o);meshes.clear();for(const o of lines.values())dispose(o);lines.clear();for(const o of zones)dispose(o);zones.length=0;for(const o of fluidMeshes)dispose(o);fluidMeshes.length=0;
  lab=next;baseline=P.validate(input);accum=0;failed=false;
  $('title').textContent=lab.config.title;['x','y','z'].forEach((k,i)=>$('w'+k).value=lab.config.wind[i]);
  for(const z of lab.config.liquids){const m=new THREE.Mesh(new THREE.BoxGeometry(...z.size),new THREE.MeshStandardMaterial({color:0x4fadd8,transparent:true,opacity:.2,depthWrite:false}));m.position.set(...z.position);zones.push(m);scene.add(m);}
  for(const h of lab.config.heaters){const m=new THREE.Mesh(new THREE.SphereGeometry(.15,12,8),new THREE.MeshBasicMaterial({color:0xff9955}));m.position.set(...h.position);zones.push(m);scene.add(m);}
  for(const f of lab.fluids)for(const b of f.particles){const m=new THREE.Mesh(new THREE.SphereGeometry(f.data.spacing*.22,8,6),new THREE.MeshStandardMaterial({color:f.data.color,roughness:.2}));m.userData.body=b;fluidMeshes.push(m);scene.add(m);}
  controls();populate();$('editor').value=JSON.stringify(baseline,null,2);
  message(lab.world.bodies.length>Math.max(48,(navigator.hardwareConcurrency||2)*24)?'This scene may run slowly on this CPU. Physical particle counts are preserved.':'Setup loaded.');
}
function line(id,points,color){let l=lines.get(id);if(!l){l=new THREE.Line(new THREE.BufferGeometry(),new THREE.LineBasicMaterial({color}));lines.set(id,l);scene.add(l);}const a=l.geometry.getAttribute('position');if(!a||a.count!==points.length)l.geometry.setAttribute('position',new THREE.Float32BufferAttribute(points.flatMap(p=>p.toArray()),3));else {points.forEach((p,i)=>a.setXYZ(i,p.x,p.y,p.z));a.needsUpdate=true;}l.geometry.computeBoundingSphere();}
function renderObjects(){
  let changed=false;
  for(const [id,m] of meshes)if(!lab.bodies.has(id)){dispose(m);meshes.delete(id);changed=true;}
  for(const [id,e] of lab.bodies){let m=meshes.get(id);if(!m){m=new THREE.Mesh(e.data.shape==='box'?new THREE.BoxGeometry(...e.data.size):new THREE.SphereGeometry(e.data.size[0]/2,20,12),new THREE.MeshStandardMaterial({color:e.data.color,roughness:.65}));scene.add(m);meshes.set(id,m);changed=true;}m.position.copy(e.body.position);m.quaternion.copy(e.body.quaternion);m.material.emissive.setHex(e.burning?0x6a2100:0);}
  if(changed)controls();
  const active=new Set();
  for(const l of lab.links)if(!l.broken){const a=lab.bodies.get(l.data.a).body.position,b=lab.bodies.get(l.data.b).body.position;let points;
    if(l.chain)points=l.chain.map(n=>n.position);
    else if(l.data.kind==='pulley')points=[a,new CANNON.Vec3(...l.data.anchor_a),new CANNON.Vec3(...l.data.anchor_b),b];
    else if(l.spring){const delta=b.vsub(a),axis=delta.unit(),ref=Math.abs(axis.y)<.9?new CANNON.Vec3(0,1,0):new CANNON.Vec3(1,0,0),u=axis.cross(ref).unit(),v=axis.cross(u).unit();points=Array.from({length:49},(_,i)=>{const t=i/48,amp=i&&i<48?.1:0;return a.vadd(delta.scale(t)).vadd(u.scale(amp*Math.sin(t*12*Math.PI))).vadd(v.scale(amp*Math.cos(t*12*Math.PI)));});}
    else points=[a,b];line(l.data.id,points,l.spring?0xe9ba64:0x9fd9d8);active.add(l.data.id);
  }
  for(const [id,l] of lines)if(!active.has(id)){dispose(l);lines.delete(id);}
  for(const m of fluidMeshes)m.position.copy(m.userData.body.position);
  let nodeCount=0;for(const l of lab.links)for(const b of l.nodes)ropePositions.set(b.position.toArray(),nodeCount++*3);
  ropeGeometry.setDrawRange(0,nodeCount);ropeGeometry.attributes.position.needsUpdate=true;
  lab.effects.forEach((p,i)=>{effectPositions.set(p.position.toArray(),i*3);const fade=p.life/p.total,color=p.kind==='smoke'?[.5,.57,.62]:p.kind==='fire'?[1,.3+fade*.4,.04]:[1,.75,.3];effectColors.set(color.map(x=>x*(.3+.7*fade)),i*3);});
  effectGeometry.setDrawRange(0,lab.effects.length);effectGeometry.attributes.position.needsUpdate=true;effectGeometry.attributes.color.needsUpdate=true;effectPoints.frustumCulled=false;
}
function snapshotForEdit(){return lab.snapshot();}
function checkedBodyChange(e,patch){const s=snapshotForEdit();Object.assign(s.objects.find(x=>x.id===e.data.id),patch);return P.validate(s).objects.find(x=>x.id===e.data.id);}
$('selection').onchange=populate;
$('add').onclick=guard(()=>{const s=snapshotForEdit(),size=values('s');if($('shape').value==='sphere')size.fill(size[0]);s.objects.push({id:lab.unique(),name:'Object',shape:$('shape').value,size,position:values('p'),mass:Number($('mass').value),color:$('color').value});const checked=P.validate(s),e=lab.addBody(checked.objects.at(-1));controls();$('selection').value=e.data.id;populate();message('Object added.');});
$('move').onclick=guard(()=>{const e=selected(),d=checkedBodyChange(e,{position:values('p')});e.body.position.set(...d.position);e.body.velocity.setZero();e.body.angularVelocity.setZero();e.body.aabbNeedsUpdate=true;message('Moved; velocity cleared.');});
$('remove').onclick=guard(()=>{lab.removeBody(selected().data.id);controls();});
$('impulse').onclick=guard(()=>{const e=selected(),v=values('i');if(!e.body.mass||!v.every(x=>Number.isFinite(x)&&Math.abs(x)<=1000))throw Error('Select a dynamic body; impulse limit ±1000 N·s per axis');e.body.applyImpulse(new CANNON.Vec3(...v));});
$('wind').onclick=guard(()=>{const wind=values('w');P.validate({...lab.config,wind});lab.config.wind=wind;message('Wind updated.');});
$('connect').onclick=guard(()=>{const a=selected(),b=lab.bodies.get($('other').value);if(!b)throw Error('Choose another body');const s=snapshotForEdit();s.connections.push({id:lab.unique('link'),kind:$('kind').value,a:a.data.id,b:b.data.id,length:Number($('length').value),stiffness:Number($('stiffness').value),damping:Number($('damping').value),break_force:Number($('breakforce').value),anchor_a:a.body.position.toArray().map((n,i)=>n+(i===1?3:0)),anchor_b:b.body.position.toArray().map((n,i)=>n+(i===1?3:0))});lab.addLink(P.validate(s).connections.at(-1));message('Connection added.');});
$('disconnect').onclick=guard(()=>{const id=selected().data.id;for(const l of lab.links)if(l.data.a===id||l.data.b===id)lab.breakLink(l);message('Selected connections released.');});
$('thermal').onclick=guard(()=>{const e=selected(),d=checkedBodyChange(e,{temperature:Number($('temperature').value),heat_capacity:Number($('capacity').value),fuel_j:Number($('fuel').value),burn_w:Number($('burn').value),break_speed:Number($('breakspeed').value)});Object.assign(e.data,d);e.temperature=d.temperature;e.fuel=d.fuel_j;message('Thermal/breakage settings updated; this is an external state edit.');});
$('ignite').onclick=guard(()=>{lab.ignite(selected().data.id);message('Ignition energy added and recorded.');});
$('emit').onclick=guard(()=>{const emitters=lab.config.emitters.map(({_acc,...d})=>d);emitters.push({position:values('p'),kind:$('effect').value});lab.config.emitters=P.validate({...lab.config,emitters}).emitters;message('Visual emitter added.');});
$('clearEmitters').onclick=()=>{lab.config.emitters=[];};
$('burst').onclick=guard(()=>{const r=lab.burst(values('p'),Number($('radius').value),Number($('burstImpulse').value));message('Burst applied once to '+r.affected+' bodies; total scalar impulse '+r.scalar_impulse_ns+' N·s.');});
function play(){if(failed)throw Error('Reset or load a setup after a stability stop');running=!running;accum=0;$('play').textContent=running?'Pause':'Run';}
$('play').onclick=guard(play);$('step').onclick=guard(()=>{if(failed)throw Error('Reset after a stability stop');running=false;$('play').textContent='Run';try{lab.step();}catch(e){failed=true;throw e;}});
$('reset').onclick=guard(()=>reset(baseline));
for(const name of Object.keys(LAB_EXAMPLES)){const o=document.createElement('option');o.value=name;o.textContent=name;$('preset').append(o);}
$('example').onclick=guard(()=>reset(LAB_EXAMPLES[$('preset').value]));
$('refresh').onclick=guard(()=>{$('editor').value=JSON.stringify(snapshotForEdit(),null,2);message('Setup read. Rope/fluid internal motion restarts on import.');});
$('apply').onclick=guard(()=>{if($('editor').value.length>250000)throw Error('Setup exceeds 250 KB');reset(JSON.parse($('editor').value));});
$('save').onclick=guard(()=>{const out=snapshotForEdit(),url=URL.createObjectURL(new Blob([JSON.stringify(out,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='portalai-physics-setup.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message('Setup exported; internal fluid/rope motion is not a checkpoint.');});
$('load').onclick=()=>$('file').click();$('file').onchange=async()=>{try{const f=$('file').files[0];if(!f)return;if(f.size>250000)throw Error('Setup exceeds 250 KB');reset(JSON.parse(await f.text()));}catch(e){message(e.message);}finally{$('file').value='';}};
$('canvas').onpointerdown=e=>{drag=[e.clientX,e.clientY];$('canvas').setPointerCapture(e.pointerId);};$('canvas').onpointermove=e=>{if(drag){yaw-=(e.clientX-drag[0])*.008;pitch=Math.max(.05,Math.min(1.5,pitch+(e.clientY-drag[1])*.008));drag=[e.clientX,e.clientY];}};$('canvas').onpointerup=()=>drag=null;$('canvas').onpointercancel=()=>drag=null;$('canvas').onwheel=e=>{e.preventDefault();distance=Math.max(4,Math.min(100,distance*Math.exp(e.deltaY*.001)));};
function frame(now){requestAnimationFrame(frame);const dt=last?Math.min((now-last)/1000,.1):0;last=now;average=.95*average+.05*dt*1000;
  if(running&&!document.hidden&&!failed){accum+=dt;let steps=0;try{while(accum>=P.STEP&&steps<10){lab.step();accum-=P.STEP;steps++;}if(steps===10)accum=0;}catch(e){running=false;failed=true;$('play').textContent='Run';message(e.message);}}
  renderObjects();camera.position.set(distance*Math.cos(pitch)*Math.sin(yaw),distance*Math.sin(pitch)+3,distance*Math.cos(pitch)*Math.cos(yaw));camera.lookAt(0,3,0);renderer.render(scene,camera);
  if(++frames%30===0){if(average>24&&quality>.6){quality=Math.max(.6,quality*.85);resize();}refreshDetails();$('status').textContent=lab.bodies.size+' rigid · '+fluidMeshes.length+' fluid · '+lab.effects.length+' visual particles\n'+lab.time.toFixed(2)+' s simulated · '+Math.round(1000/Math.max(average,1))+' fps · '+lab.broken+' released links\nHeater '+lab.energy.heater_j.toFixed(0)+' J · fuel '+lab.energy.fuel_j.toFixed(0)+' J · ignition '+lab.energy.ignition_j.toFixed(0)+' J'+(lab.events.length?'\n'+lab.events.at(-1):'');}
}
window.addEventListener('resize',resize);document.addEventListener('visibilitychange',()=>{accum=0;last=0;});
try{reset(LAB_INITIAL);resize();requestAnimationFrame(frame);}catch(e){message('Physics Lab could not start: '+e.message);}

} catch(error) { document.getElementById('message').textContent='Physics Lab could not start: '+error.message; }
