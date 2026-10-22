import {readFile,writeFile,mkdir} from 'node:fs/promises';
let bundle='// PortalAI desktop card 0.5.12. HA-only build; no host changes.\n';
for(const name of ['browser-crypto.js','visibility-grace.js','portalai-projection.js']){
  const source=(await readFile(new URL('web/'+name,import.meta.url),'utf8')).replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'');
  bundle+=source+'\n';
}
await mkdir(new URL('dist/',import.meta.url),{recursive:true});
await writeFile(new URL('dist/portalai-projection-v0.5.12.js',import.meta.url),bundle);
console.log('Built desktop card: '+Buffer.byteLength(bundle)+' bytes');
