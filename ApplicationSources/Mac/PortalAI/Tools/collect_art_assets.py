"""Copy public application artwork into an indexed, checksum-verified gallery."""
import hashlib
import html
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from runtime_policy import require_space

def main():
    sources=sorted((ROOT/'ControlCenter/Branding').glob('*'))
    sources=[p for p in sources if p.suffix.lower() in ('.png','.ico','.svg','.jpg','.webp')]
    sources.append(ROOT/'ControlCenter/PortableAI.ico')
    require_space(ROOT,sum(p.stat().st_size for p in sources)*2,for_outputs=True)
    dest=ROOT/'Art Assets';dest.mkdir(exist_ok=True)
    if dest.is_symlink() or dest.is_junction():raise ValueError('Linked art destination refused')
    rows=[]
    for source in sources:
        if source.is_symlink() or source.is_junction():raise ValueError('Linked public art refused')
        group=('Icons' if source.suffix=='.ico' or 'Icon' in source.name else
               'Wordmarks' if 'Wordmark' in source.name else
               'Watermarks' if 'Watermark' in source.name else
               'Emblems' if 'Emblem' in source.name else 'Interface art')
        target=dest/group/source.name.replace('PortableAI','PortalAI')
        if source.parent==ROOT/'ControlCenter':target=target.with_name('PortalAI_Launcher.ico')
        target.parent.mkdir(exist_ok=True)
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
            raise ValueError('Existing different artwork preserved: '+str(target))
        if not target.exists():shutil.copy2(source,target)
        assert hashlib.sha256(target.read_bytes()).hexdigest()==digest
        rows.append({'file':target.relative_to(dest).as_posix(),'source':source.relative_to(ROOT).as_posix(),
                     'bytes':target.stat().st_size,'sha256':digest})
    (dest/'manifest.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
    (dest/'READ ME.txt').write_text('PortalAI art assets\n\nOpen Gallery.html for a visual index.\n\n'
        'These are verified copies of public launcher assets. Application originals remain in ControlCenter/Branding and ControlCenter.\n'
        'Emblems: dark, bright and clean variants, including the original source image.\n'
        'Wordmarks: banner, welcome and compact variants. Icons: launcher/tray .ico and PNG artwork.\n'
        'Watermarks: light/dark chat/page versions. Interface art: earlier welcome/header/corner variants.\n'
        'Sizes in filenames are pixel dimensions used by the GUI. Transparency is visible against the gallery checkerboard.\n'
        'No private account images or model/runtime assets are included. manifest.json records each original and SHA-256.\n',encoding='utf-8')
    cards=''.join('<figure><a href="'+html.escape(r['file'],quote=True)+'"><img src="'+html.escape(r['file'],quote=True)+'" alt="'+html.escape(Path(r['file']).stem)+'"></a><figcaption>'+html.escape(r['file'])+'</figcaption></figure>' for r in rows)
    (dest/'Gallery.html').write_text('<!doctype html><meta charset="utf-8"><title>PortalAI art assets</title>'
        '<style>body{background:#f8f3ea;color:#282622;font:16px system-ui;margin:32px}main{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:20px}figure{margin:0;border:1px solid #a87d32;border-radius:14px;padding:16px;overflow-wrap:anywhere}img{width:100%;height:220px;object-fit:contain;background:repeating-conic-gradient(#ddd 0% 25%,#fafafa 0% 50%) 0/20px 20px}figcaption{padding-top:12px}</style>'
        '<h1>PortalAI art assets</h1><p>Click an image to open its full-size copy. Original application files remain in place.</p><main>'+cards+'</main>',encoding='utf-8')
    print(json.dumps({'copies':len(rows),'verified':True,'directory':str(dest),'bytes':sum(r['bytes'] for r in rows)}))

if __name__=='__main__':main()
