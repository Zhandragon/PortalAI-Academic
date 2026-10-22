import {readFile,writeFile,mkdir} from 'node:fs/promises';
let bundle='// PortalAI quick chat 0.4.3. No credentials or sample state.\n';
for(const [name,exports] of [['browser-crypto.js',['randomId','sha256Hex']],['catalog.js',['CATALOG']],['portalai-viewer-demand.js',['PortalAIViewerDemand']],['live-state.js',['LiveSession']],['patch-dom.js',['patchMarkup']],['rich-chat.js',['RichChat']],['portalai-quick-card.js',[]]]){
  const source=(await readFile(new URL('web/'+name,import.meta.url),'utf8')).replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'');
  bundle+=(exports.length?'const {'+exports.join(',')+'}=':'')+'(()=>{\n'+source+'\n'+(exports.length?'return {'+exports.join(',')+'};':'')+'\n})();\n';
}
await mkdir(new URL('dist/',import.meta.url),{recursive:true});
await writeFile(new URL('dist/portalai-quick-chat-v0.4.3.js',import.meta.url),bundle);
console.log('Built quick-chat bundle: '+Buffer.byteLength(bundle)+' bytes');
