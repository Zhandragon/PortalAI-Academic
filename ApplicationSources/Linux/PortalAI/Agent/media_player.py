"""Self-contained loopback media player; no remote assets or dependencies."""
from html import escape
import re
import secrets


def player_document(source, title, kind):
    if kind not in ('audio', 'video') or not source.startswith('/') or source.startswith('//'):
        raise ValueError('Player requires a same-origin local audio/video source')
    nonce = secrets.token_urlsafe(24)
    safe_source, safe_title = escape(source, quote=True), escape(title)
    html = '''<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PortalAI media · TITLE</title>
<style nonce="NONCE">
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;padding:24px;background:#17191c;color:#eee9df;font:16px system-ui,sans-serif}
main{max-width:1100px;margin:auto;padding:22px;border:2px solid #b88a32;border-radius:18px;background:#212326}
h1{font-size:20px;overflow-wrap:anywhere;color:#dfc17b}video,audio{display:block;width:100%;max-height:65vh;background:#000;border-radius:8px}
.transport{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:16px}button,a{padding:8px 12px;border:1px solid #b88a32;border-radius:6px;background:#303338;color:inherit;text-decoration:none;cursor:pointer}
button:disabled,input:disabled{opacity:.5;cursor:default}button:focus-visible,a:focus-visible,input:focus-visible{outline:3px solid #39b5c9;outline-offset:3px}
.timeline{display:flex;gap:12px;align-items:center;margin-top:16px}.timeline input{min-width:60px;flex:1;accent-color:#39b5c9;cursor:pointer}.time{font-variant-numeric:tabular-nums;white-space:nowrap}
#status{min-height:1.5em;color:#d3c8b6}.hint{font-size:14px;color:#beb6a8}
</style><main><h1>TITLE</h1>
<KIND id="media" controls preload="metadata" playsinline src="SOURCE"></KIND>
<div class="transport"><button id="play" type="button">Play</button><button id="back" type="button" disabled>−10 seconds</button><button id="forward" type="button" disabled>+10 seconds</button><a href="SOURCE" download>Download file</a></div>
<div class="timeline"><span id="position" class="time">0:00</span><input id="seek" type="range" min="0" max="0" step="0.1" value="0" aria-label="Playback position" disabled><span id="duration" class="time">0:00</span></div>
<p id="status" role="status" aria-live="polite">Reading media metadata…</p><p class="hint">Click or drag the timeline to seek. Focus it and use the arrow keys for precise positioning. Downloads and playback remain tied to this PortalAI login.</p>
</main><script nonce="NONCE">
'use strict';
const media=document.getElementById('media'), seek=document.getElementById('seek'), play=document.getElementById('play'), back=document.getElementById('back'), forward=document.getElementById('forward'), status=document.getElementById('status');
const clock=s=>{s=Math.max(0,Math.floor(Number(s)||0));return (s>=3600?Math.floor(s/3600)+':':'')+String(Math.floor(s/60)%60).padStart(s>=3600?2:1,'0')+':'+String(s%60).padStart(2,'0');};
let dragging=false;
function refresh(){
 const ready=Number.isFinite(media.duration)&&media.duration>0;
 seek.disabled=back.disabled=forward.disabled=!ready;
 if(ready){seek.max=String(media.duration);document.getElementById('duration').textContent=clock(media.duration);}
 if(!dragging)seek.value=String(media.currentTime||0);
 document.getElementById('position').textContent=clock(media.currentTime);
 play.textContent=media.paused?'Play':'Pause';
}
function jump(value){
 if(!Number.isFinite(media.duration)||media.duration<=0)return;
 const target=Math.max(0,Math.min(media.duration,Number(value)));
 if(!Number.isFinite(target))return;
 try{media.currentTime=target;status.textContent='Seeking to '+clock(target)+'…';refresh();}
 catch(error){status.textContent='This media could not seek yet. Wait for metadata or download the file.';}
}
seek.addEventListener('pointerdown',()=>dragging=true);
window.addEventListener('pointerup',()=>{dragging=false;refresh();});
window.addEventListener('pointercancel',()=>{dragging=false;refresh();});
seek.addEventListener('input',()=>jump(seek.value));
seek.addEventListener('change',()=>{jump(seek.value);dragging=false;refresh();});
play.addEventListener('click',async()=>{if(!media.paused){media.pause();return;}try{await media.play();}catch(error){status.textContent='Playback could not start. Check that your PortalAI login is still open, or download the file.';}});
back.addEventListener('click',()=>jump(media.currentTime-10));forward.addEventListener('click',()=>jump(media.currentTime+10));
for(const name of ['loadedmetadata','durationchange','timeupdate','play','pause','ended'])media.addEventListener(name,refresh);
media.addEventListener('loadedmetadata',()=>status.textContent='Ready.');
media.addEventListener('seeking',()=>status.textContent='Seeking…');
media.addEventListener('seeked',()=>{status.textContent='Position updated.';refresh();});
media.addEventListener('waiting',()=>status.textContent='Loading the requested portion of the file…');
media.addEventListener('playing',()=>status.textContent='Playing.');
media.addEventListener('error',()=>{status.textContent='The file could not be played. Your login may have ended, or this browser may not support its codec. Download it while signed in to use another player.';seek.disabled=back.disabled=forward.disabled=true;});
refresh();
</script></html>'''
    # Substitute only fixed placeholders before inserting user filenames/URLs.
    replacements = {'NONCE':nonce, 'KIND':kind, 'TITLE':safe_title, 'SOURCE':safe_source}
    html = re.sub(r'NONCE|KIND|TITLE|SOURCE', lambda match:replacements[match[0]], html)
    csp = ("default-src 'none'; media-src 'self'; script-src 'nonce-"+nonce+
           "'; style-src 'nonce-"+nonce+"'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
    return html.encode('utf-8'), csp
