// Deterministic single-module deployment bundle; test harness is never included.
import {readFile,writeFile,mkdir} from 'node:fs/promises';
const root=new URL('./',import.meta.url);
const read=name=>readFile(new URL(name,root),'utf8');
const modules=[['browser-crypto.js',['randomId','sha256Hex']],['catalog.js',['CATALOG']],['state.js',['PanelState','fixtureSnapshot']],['visibility-grace.js',['VisibilityGrace']],['portalai-viewer-demand.js',['PortalAIViewerDemand']],['live-state.js',['LiveSession']],['patch-dom.js',['patchMarkup']],['rich-chat.js',['RichChat']],['iphone-attachments.js',['isIPhone','attachmentPickerMarkup','attachmentPickerCSS']],['native-workflows.js',[]],['portalai-native-panel.js',['PortalAINativePanel']],['portalai-live-panel.js',[]]];
const css=await read('web/panel.css');
const images={};
for (const name of ['icon.png','emblem.png','wordmark.png']) images[name]='data:image/png;base64,'+(await readFile(new URL('web/assets/'+name,root))).toString('base64');
let bundle='// PortalAI native UI 0.5.11, native workflows. Built from reviewed local modules.\n';
bundle+='const PANEL_CSS='+JSON.stringify(css)+';\nconst PANEL_IMAGES='+JSON.stringify(images)+';\n';
for (const [name,exports] of modules) {
  let source=(await read('web/'+name)).replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'');
  if (name==='portalai-native-panel.js') {
    source=source.replace("const asset = name => new URL(`./assets/${name}`, import.meta.url).href;",'const asset = name => PANEL_IMAGES[name];');
    source=source.replace('<link rel="stylesheet" href="${new URL(\'./panel.css\',import.meta.url).href}">','<style>${PANEL_CSS}</style>');
  }
  bundle+=(exports.length?'const {'+exports.join(',')+'}=':'')+'(()=>{\n'+source+'\n'+(exports.length?'return {'+exports.join(',')+'};':'')+'\n})();\n';
}
await mkdir(new URL('dist/',root),{recursive:true});
await writeFile(new URL('dist/portalai-live-v0.5.11.js',root),bundle);
console.log('Built dist/portalai-live-v0.5.11.js ('+Buffer.byteLength(bundle)+' bytes)');
