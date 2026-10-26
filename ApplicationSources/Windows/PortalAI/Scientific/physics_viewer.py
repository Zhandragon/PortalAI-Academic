"""Offline, dependency-free playback of bounded synthetic mechanics frames."""
import json


def document(result):
    data = json.dumps(result, separators=(',', ':'), allow_nan=False).replace('<', '\\u003c')
    return '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PortalAI · Coupled physics demo</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;padding:20px;background:#17191b;color:#eee6d6;font:16px system-ui}
main{max-width:1050px;margin:auto;border:2px solid #b88a32;border-radius:18px;padding:20px;background:#212326}h1{font:600 26px Georgia;color:#e0bd67}
canvas{display:block;width:100%;height:min(62vh,650px);background:#101419;border:1px solid #b88a32;border-radius:14px;touch-action:none}
.row{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin:14px 0}input{flex:1;min-width:180px;accent-color:#e0bd67}
button{padding:8px 18px;border:1px solid #b88a32;border-radius:8px;background:#34312a;color:#fff;cursor:pointer}button:focus-visible,input:focus-visible{outline:3px solid #40b5cf}
.note{color:#d6c7a6;font-size:14px;line-height:1.5}details{border:1px solid #b88a32;border-radius:12px;padding:12px}li{margin:7px 0}#clock{min-width:120px;font-variant-numeric:tabular-nums}
</style><main><h1>PortalAI · Coupled physics</h1>
<p class="note">A bounded demonstration of a water-like liquid, an elastic block and a moving rigid object. This is an approximate educational solver, not validated engineering analysis.</p>
<canvas id="scene" aria-label="Physics particle animation"></canvas>
<div class="row"><button id="play">Play</button><input id="frame" type="range" min="0" value="0" step="1" aria-label="Simulation time"><span id="clock"></span><button id="reset">Reset view</button></div>
<p class="note" id="legend"></p><p class="note" id="metrics"></p>
<details><summary>Assumptions and limits</summary><ul id="limits"></ul></details></main>
<script>
'use strict';const D=__DATA__, canvas=document.getElementById('scene'),ctx=canvas.getContext('2d'),slider=document.getElementById('frame'),play=document.getElementById('play');
let frame=0,playing=false,last=0,elapsed=0,yaw=.55,pitch=.3,drag=null;
slider.max=D.frames.length-1;
document.getElementById('legend').textContent='Blue: water-like liquid · Coral: elastic block · Gold: rigid object. '+(D.config.dimensions===3?'Drag to orbit the 3D view.':'2D slice, one-metre thickness.')+' Drag the timeline to inspect a saved frame.';
document.getElementById('metrics').textContent=D.particle_count+' particles · '+D.config.grid+' cells per axis · CPU · '+D.metrics.steps+' integration steps · maximum liquid volume change '+(100*D.metrics.maximum_liquid_volume_change_fraction).toFixed(1)+'% (compressibility/error diagnostic).';
for(const value of D.limitations){const li=document.createElement('li');li.textContent=value;document.getElementById('limits').appendChild(li);}
function project(p){let x=p[0]-.5,y=p[D.config.dimensions-1]-.5,z=0;
 if(D.config.dimensions===3){z=p[1]-.5;const xx=x*Math.cos(yaw)-z*Math.sin(yaw),zz=x*Math.sin(yaw)+z*Math.cos(yaw),yy=y;x=xx;y=yy*Math.cos(pitch)-zz*Math.sin(pitch);z=yy*Math.sin(pitch)+zz*Math.cos(pitch);}
 const scale=Math.min(canvas.width,canvas.height)*.7;return[canvas.width/2+x*scale,canvas.height/2-y*scale,z,scale];}
function draw(){const r=canvas.getBoundingClientRect(),ratio=Math.min(devicePixelRatio||1,2);canvas.width=Math.max(1,Math.round(r.width*ratio));canvas.height=Math.max(1,Math.round(r.height*ratio));ctx.clearRect(0,0,canvas.width,canvas.height);
 const bounds=D.tank_bounds_m,corners=[];for(let i=0;i<(1<<D.config.dimensions);i++)corners.push(Array.from({length:D.config.dimensions},(_,k)=>bounds[(i>>k)&1]));ctx.strokeStyle='#6c613d';ctx.lineWidth=ratio;
 for(let i=0;i<corners.length;i++)for(let j=i+1;j<corners.length;j++)if(corners[i].filter((v,k)=>v!==corners[j][k]).length===1){const a=project(corners[i]),b=project(corners[j]);ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();}
 const f=D.frames[frame],points=f.positions.map((p,i)=>({p:project(p),material:D.materials[i]}));points.push({p:project(f.rigid_center),rigid:true});points.sort((a,b)=>a.p[2]-b.p[2]);
 for(const item of points){ctx.fillStyle=item.rigid?'#bc9139':item.material?'#f09683':'#39b8df';ctx.beginPath();ctx.arc(item.p[0],item.p[1],item.rigid?D.rigid_radius_m*item.p[3]:Math.max(1.5*ratio,item.p[3]/D.config.grid*.3),0,Math.PI*2);ctx.fill();if(item.rigid){ctx.strokeStyle='#f7d17c';ctx.lineWidth=2*ratio;ctx.stroke();}}
 document.getElementById('clock').textContent=f.time_s.toFixed(3)+' / '+D.config.duration_s.toFixed(3)+' s';slider.value=frame;
}
play.onclick=()=>{playing=!playing;play.textContent=playing?'Pause':'Play';last=0;if(playing&&frame===D.frames.length-1){frame=0;elapsed=0;}else elapsed=D.frames[frame].time_s;};
slider.oninput=()=>{playing=false;play.textContent='Play';frame=Number(slider.value);draw();};
canvas.onpointerdown=e=>{drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);};canvas.onpointerup=canvas.onpointercancel=()=>drag=null;
canvas.onpointermove=e=>{if(drag&&D.config.dimensions===3){yaw+=(e.clientX-drag[0])*.008;pitch=Math.max(-1.1,Math.min(1.1,pitch+(e.clientY-drag[1])*.008));drag=[e.clientX,e.clientY];draw();}};
document.getElementById('reset').onclick=()=>{yaw=.55;pitch=.3;draw();};window.addEventListener('resize',draw);
function tick(now){if(playing){if(last)elapsed+=(now-last)/1000;frame=Math.min(D.frames.length-1,Math.floor(elapsed/D.config.duration_s*(D.frames.length-1)));draw();if(frame===D.frames.length-1){playing=false;play.textContent='Play';}}last=now;requestAnimationFrame(tick);}draw();requestAnimationFrame(tick);
</script></html>'''.replace('__DATA__', data)
