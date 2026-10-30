"""Offline interactive previews with an opaque-origin, scripts-only iframe."""
import html
import json
from artifacts import validate_content

CSP="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; frame-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"

CHART=r'''<!doctype html><meta charset="utf-8"><style>body{font:15px system-ui;background:#171b1e;color:#edf3f5;margin:20px}button{background:#29333c;color:inherit;border:1px solid #819199;border-radius:8px;padding:8px;margin:4px}button[aria-pressed=false]{opacity:.4}svg{width:100%;height:400px}#tip{min-height:25px}text{fill:#c9d8df;font-size:12px}</style><h2 id="title"></h2><div id="legend"></div><svg id="plot" viewBox="0 0 900 400" role="img" aria-label="Interactive chart"></svg><p id="tip">Toggle series or hover a point.</p><script>
const data=__DATA__;const on=data.series.map(()=>true),colors=['#62d2ba','#edc06d','#76abec','#e995bf','#a5cf73','#af9fe4'];
document.getElementById('title').textContent=data.title||'Chart';
const svg=document.getElementById('plot');function el(tag,attrs,text){const e=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;svg.appendChild(e);return e}
function draw(){svg.replaceChildren();let vals=data.series.flatMap((s,i)=>on[i]?s.values:[]),lo=Math.min(0,...vals),hi=Math.max(1,...vals),span=hi-lo||1;
const x=i=>60+i*800/Math.max(1,data.labels.length-1),y=v=>350-(v-lo)*300/span;
for(let t=0;t<=4;t++){let v=lo+span*t/4;el('line',{x1:55,y1:y(v),x2:870,y2:y(v),stroke:'#394750'});el('text',{x:3,y:y(v)+4},v.toPrecision(3))}
data.labels.forEach((v,i)=>{if(i%Math.max(1,Math.ceil(data.labels.length/8))===0)el('text',{x:x(i),y:375,'text-anchor':'middle'},v.slice(0,18))});
data.series.forEach((s,j)=>{if(!on[j])return;let color=colors[j%colors.length];if(data.style!=='bar')el('polyline',{points:s.values.map((v,i)=>x(i)+','+y(v)).join(' '),fill:'none',stroke:color,'stroke-width':2});
s.values.forEach((v,i)=>{const bar=data.style==='bar',w=Math.max(1,700/data.labels.length/data.series.length);const p=bar?el('rect',{x:x(i)+(j-data.series.length/2)*w,y:Math.min(y(v),y(0)),width:w,height:Math.max(1,Math.abs(y(v)-y(0))),fill:color}):el('circle',{cx:x(i),cy:y(v),r:4,fill:color});p.addEventListener('mouseenter',()=>document.getElementById('tip').textContent=s.name+' — '+data.labels[i]+': '+v)})})}
data.series.forEach((s,i)=>{let b=document.createElement('button');b.textContent=s.name;b.setAttribute('aria-pressed','true');b.onclick=()=>{on[i]=!on[i];b.setAttribute('aria-pressed',String(on[i]));draw()};document.getElementById('legend').appendChild(b)});draw();</script>'''


def inner_document(kind,content):
    validate_content(kind,content)
    if kind=='chart':content=CHART.replace('__DATA__',json.dumps(json.loads(content),ensure_ascii=True).replace('<','\\u003c'))
    elif kind=='svg':content='<html><body style="margin:0;background:white">'+content+'</body></html>'
    return '<!doctype html><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="'+html.escape(CSP,quote=True)+'">'+content


def preview_document(title,kind,content):
    inner=inner_document(kind,content)
    return '''<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; frame-src about:; connect-src 'none'; worker-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"><title>PortalAI artifact preview</title><style>body{margin:0;background:#171b1e;color:#eef3f5;font:14px system-ui}header{padding:12px}iframe{border:0;width:100%;height:calc(100vh - 60px);background:white}</style></head><body><header>'''+html.escape(title)+''' · Isolated preview · Network, files, forms and downloads disabled</header><iframe title="Artifact preview" sandbox="allow-scripts" referrerpolicy="no-referrer" allow="camera 'none'; microphone 'none'; geolocation 'none'; clipboard-read 'none'; clipboard-write 'none'; payment 'none'; usb 'none'; serial 'none'; hid 'none'" srcdoc="'''+html.escape(inner,quote=True)+'''"></iframe></body></html>'''
