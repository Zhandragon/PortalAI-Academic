"""Pinned offline Markdown, Mermaid and React renderers, loaded only on preview."""
import hashlib
import json
import re
from pathlib import Path

ASSETS=Path(__file__).resolve().parents[1]/'ControlCenter/ArtifactAssets'


def asset(name):
    manifest=json.loads((ASSETS/'manifest.json').read_text())
    row=next((r for r in manifest['files'] if r['file']==name),None)
    if row is None or row['bytes']>8*1024**2:raise ValueError('Unknown or oversized preview asset')
    data=(ASSETS/name).read_bytes()
    if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Preview asset integrity check failed')
    return data.decode('utf-8').replace('</script','<\\/script')


def script(value):
    # HTML recognizes closing script tags without regard to case, including in
    # JavaScript strings/comments. Escape only the slash, preserving JS text.
    value=re.sub(r'</script',lambda match:'<\\/'+match.group(0)[2:],value,flags=re.IGNORECASE)
    return '<script>'+value+'</script>'


def document(kind,content,modules=()):
    source=json.dumps(content,ensure_ascii=True).replace('<','\\u003c')
    head='''<style>body{font:16px system-ui;margin:20px;background:#f4ede1;color:#232725}a{color:#167d83}pre{padding:12px;overflow:auto;background:#e7dfd1}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #b9ad94}img,svg{max-width:100%}button{padding:8px 14px;border-radius:8px}</style><div id="portalai-render-status" data-state="loading">Rendering…</div><main id="root"></main>'''
    finish="document.getElementById('portalai-render-status').dataset.state='ready';document.getElementById('portalai-render-status').textContent='';"
    failure="const s=document.getElementById('portalai-render-status');s.dataset.state='error';s.textContent=String(error);"
    if kind=='markdown':
        return head+script(asset('marked-marked.umd.js'))+script(asset('dompurify-purify.min.js'))+script(
            'try{document.getElementById("root").innerHTML=DOMPurify.sanitize(marked.parse('+source+'),{USE_PROFILES:{html:true},FORBID_TAGS:["form","input","button","style"],FORBID_ATTR:["style"]});'+finish+'}catch(error){'+failure+'}')
    if kind=='mermaid':
        return head+script(asset('mermaid-js-tiny-mermaid.tiny.js'))+script(
            'mermaid.initialize({startOnLoad:false,securityLevel:"strict",theme:"neutral",maxTextSize:50000,maxEdges:500,secure:["secure","securityLevel","startOnLoad","maxTextSize","maxEdges"]});'
            '(async()=>{try{const result=await mermaid.render("portalaiDiagram",'+source+');document.getElementById("root").innerHTML=result.svg;'+finish+'}catch(error){'+failure+'}})();')
    if kind=='react':
        code='window.__portalModules=Object.create(null);window.__portalFactories=Object.create(null);function __portalRequire(name){if(Object.prototype.hasOwnProperty.call(window.__portalModules,name))return window.__portalModules[name];if(!Object.prototype.hasOwnProperty.call(window.__portalFactories,name))throw new Error("Unavailable offline module: "+name);var module={exports:{}};window.__portalModules[name]=module.exports;try{window.__portalFactories[name](module,module.exports,__portalRequire);return window.__portalModules[name]=module.exports;}catch(error){delete window.__portalModules[name];throw error;}}\n'
        for name,filename in [('react','react-react.production.js'),('scheduler','scheduler-scheduler.production.js'),
                              ('react-dom','react-dom-react-dom.production.js'),('react-dom/client','react-dom-react-dom-client.production.js')]:
            code+='(function(){var module={exports:{}};var exports=module.exports;var require=__portalRequire;var process={env:{NODE_ENV:"production"}};\n'+asset(filename)+'\nwindow.__portalModules['+json.dumps(name)+']=module.exports;})();\n'
        for module in modules:
            # Register factories before evaluating imports, including circular ones.
            # Code is deliberately confined to the opaque, offline iframe.
            code+='window.__portalFactories['+json.dumps(module['name'])+']=function(module,exports,require){var process={env:{NODE_ENV:"production"}};\n'+module['source'].replace('</script','<\\/script')+'\n};\n'
        prefix='(function(){var exports={};var module={exports:exports};var require=__portalRequire;var React=require("react");try{\n'
        suffix='\nvar Component=module.exports.default||exports.default||(typeof App!=="undefined"?App:null);if(!Component)throw new Error("Export a default React component or define App");require("react-dom/client").createRoot(document.getElementById("root")).render(React.createElement(Component));'+finish+'}catch(error){'+failure+'}})();'
        compiler='try{const compiled=Babel.transform('+source+',{presets:[["react",{runtime:"classic"}]],plugins:["transform-modules-commonjs"],filename:"artifact.jsx"}).code;const run=document.createElement("script");run.textContent='+json.dumps(prefix)+'+compiled+'+json.dumps(suffix)+';document.body.appendChild(run);}catch(error){'+failure+'}'
        return head+script(code)+script(asset('babel-standalone-babel.min.js'))+script(compiler)
    raise ValueError('Unknown rich artifact type')
