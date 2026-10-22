// Local-only fixture; no credentials, real account, or host requests.
import http from 'node:http';
import {readFile} from 'node:fs/promises';
const files={'/full.js':'dist/portalai-live-v0.5.12.js','/fixture.js':'tests/iphone-review-fixture.js'};
const server=http.createServer(async(req,res)=>{
  const path=new URL(req.url,'http://localhost').pathname;
  if(req.method!=='GET'){res.writeHead(405).end();return;}
  res.setHeader('Cache-Control','no-store');
  if(path==='/'){res.setHeader('Content-Type','text/html');res.end('<!doctype html><meta name="viewport" content="width=device-width,initial-scale=1"><title>iPhone attachment local fixture</title><script type="module" src="/fixture.js"></script>');return;}
  if(!files[path]){res.writeHead(404).end();return;}
  res.setHeader('Content-Type','text/javascript');res.end(await readFile(new URL('../'+files[path],import.meta.url)));
});
server.listen(0,'127.0.0.1',()=>console.log('Attachment fixture: http://127.0.0.1:'+server.address().port+'/'));
