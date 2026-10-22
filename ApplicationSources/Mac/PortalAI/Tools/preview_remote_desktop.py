"""Loopback-only browser fixture. Serves three reviewed, synthetic resources."""
from http.server import HTTPServer,BaseHTTPRequestHandler
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"><style>body{margin:0;background:#101620;color:#eee}portalai-desktop{height:100dvh!important}</style></head><body><portalai-desktop></portalai-desktop><script type="module">
import '/card.js';
const frames={};for(const name of ['screen','compact','landscape']){const blob=await(await fetch('/'+name+'.png')).blob();const png=await new Promise(resolve=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.readAsDataURL(blob)});const image=new Image();image.src='data:image/png;base64,'+png;await image.decode();frames[name]={png,width:image.naturalWidth,height:image.naturalHeight}}
const card=document.querySelector('portalai-desktop');card.setConfig({title:'PortalAI / synthetic preview'});
let view='screen';card.hass={callWS:async command=>{if(command.action==='input'&&command.payload.event.kind==='layout')view=command.payload.event.view==='portrait_chat'?'compact':'landscape';if(command.action==='frame')return {...frames[view],profile_open:true,window:'synthetic',windows:[{id:'synthetic',title:'PortalAI — disposable account'}]};return {accepted:true}}};
</script></body></html>'''.encode('utf-8')
class Handler(BaseHTTPRequestHandler):
    def log_message(self,*_):pass
    def do_GET(self):
        if self.path=='/':data=HTML;mime='text/html'
        elif self.path=='/card.js':data=(ROOT/'HomeAssistant/ha/www/portalai-desktop.js').read_bytes();mime='text/javascript'
        elif self.path=='/screen.png':data=(ROOT/'Maintenance/Validation/HomeAssistantLogin/login-shell.png').read_bytes();mime='image/png'
        elif self.path=='/compact.png':data=(ROOT/'Maintenance/Validation/HomeAssistantLogin/phone-portrait-chat.png').read_bytes();mime='image/png'
        elif self.path=='/landscape.png':data=(ROOT/'Maintenance/Validation/HomeAssistantLogin/phone-landscape-full.png').read_bytes();mime='image/png'
        else:self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type',mime+'; charset=utf-8' if mime.startswith('text/') else mime);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
if __name__=='__main__':
    server=HTTPServer(('127.0.0.1',0),Handler)
    print(f'http://127.0.0.1:{server.server_port}/',flush=True)
    try:server.serve_forever()
    finally:server.server_close()
