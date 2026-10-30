"""Bounded local extraction with page/slide/sheet locations and optional scan OCR."""
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET

TEXT={'.txt','.md','.rst','.csv','.tsv','.json','.jsonl','.xml','.html','.htm','.py'}
SUPPORTED=TEXT|{'.pdf','.docx','.xlsx','.pptx','.png','.jpg','.jpeg','.tif','.tiff','.bmp'}
MAX_TEXT=8*1024**2


def _office(path):
    with zipfile.ZipFile(path) as z:
        infos=z.infolist()
        if len(infos)>10000 or sum(x.file_size for x in infos)>128*1024**2:raise ValueError('Office archive exceeds extraction limits')
        def xml(name):
            data=z.read(name)
            if b'<!DOCTYPE' in data or b'<!ENTITY' in data:raise ValueError('XML entities are not supported')
            return ET.fromstring(data)
        def texts(node):return '\n'.join(e.text for e in node.iter() if e.tag.rsplit('}',1)[-1]=='t' and e.text)
        if path.suffix.lower()=='.docx':return [('document',texts(xml('word/document.xml')))]
        if path.suffix.lower()=='.pptx':
            import re,posixpath
            names=sorted((n for n in z.namelist() if re.fullmatch('ppt/slides/slide[0-9]+.xml',n)),key=lambda n:int(re.search(r'slide(\d+)',n).group(1)))
            if 'ppt/presentation.xml' in z.namelist():
                rels={e.get('Id'):e.get('Target') for e in xml('ppt/_rels/presentation.xml.rels')}
                names=[posixpath.normpath('ppt/'+rels[e.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')])
                       for e in xml('ppt/presentation.xml').iter() if e.tag.rsplit('}',1)[-1]=='sldId']
            return [('slide '+str(i+1),texts(xml(n))) for i,n in enumerate(names)]
        shared=[texts(e).replace('\n',' ') for e in xml('xl/sharedStrings.xml')] if 'xl/sharedStrings.xml' in z.namelist() else []
        ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        rels={e.get('Id'):e.get('Target') for e in xml('xl/_rels/workbook.xml.rels')}
        out=[]
        for sheet in xml('xl/workbook.xml').findall('m:sheets/m:sheet',ns):
            rid=sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
            target=rels[rid];name=target.lstrip('/') if target.startswith('/') else 'xl/'+target
            rows=[]
            for row in xml(name).findall('.//m:row',ns):
                cells=[]
                for c in row.findall('m:c',ns):
                    value=c.findtext('m:v','',ns)
                    if c.get('t')=='s':value=shared[int(value)]
                    elif c.get('t')=='inlineStr':value=texts(c)
                    cells.append(c.get('r','')+': '+value)
                rows.append(' | '.join(cells))
            out.append(('sheet '+sheet.get('name',''), '\n'.join(rows)))
        return out


def extract(root, path, check=lambda:None, ocr=True):
    path=Path(path);ext=path.suffix.lower();check()
    if ext not in SUPPORTED:raise ValueError('Unsupported document type: '+ext)
    if path.stat().st_size>100*1024**2:raise ValueError('Document exceeds 100 MiB')
    if ext in TEXT:
        if path.stat().st_size>MAX_TEXT:raise ValueError('Text document exceeds 8 MiB')
        text=path.read_text(encoding='utf-8-sig',errors='replace')
        if ext in ('.html','.htm'):
            from html.parser import HTMLParser
            class Text(HTMLParser):
                def __init__(self):super().__init__();self.parts=[];self.skip=0
                def handle_starttag(self,tag,attrs):
                    if tag in ('script','style'):self.skip+=1
                def handle_endtag(self,tag):
                    if tag in ('script','style'):self.skip=max(0,self.skip-1)
                def handle_data(self,data):
                    if not self.skip:self.parts.append(data)
            parser=Text();parser.feed(text);text='\n'.join(parser.parts)
        pages=[('text',text)]
    elif ext in ('.docx','.xlsx','.pptx'):pages=_office(path)
    else:
        from knowledge_embeddings import packages
        packages(root)
        engine=None
        def recognize(image):
            nonlocal engine
            if not ocr:raise ValueError('This page needs OCR; enable local OCR for this collection')
            from rapidocr_onnxruntime import RapidOCR
            if engine is None:engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=1)
            result,_=engine(image)
            return '\n'.join(row[1] for row in result or [])
        if ext=='.pdf':
            import pypdfium2 as pdfium
            pdf=pdfium.PdfDocument(str(path));pages=[]
            try:
                if len(pdf)>1000:raise ValueError('PDF exceeds 1000 pages')
                for i in range(len(pdf)):
                    check();page=pdf[i]
                    try:
                        textpage=page.get_textpage()
                        try:text=textpage.get_text_range()
                        finally:textpage.close()
                        if len(text.strip())<15:
                            width,height=page.get_size();scale=min(2,2500/max(width,height))
                            bitmap=page.render(scale=scale)
                            try:
                                import numpy as np
                                text=recognize(np.array(bitmap.to_pil().convert('RGB')))
                            finally:bitmap.close()
                        pages.append(('page '+str(i+1),text))
                        if sum(len(t) for _,t in pages)>MAX_TEXT:raise ValueError('Extracted PDF exceeds 8 MiB')
                    finally:page.close()
            finally:pdf.close()
        else:
            from PIL import Image
            import numpy as np
            with Image.open(path) as image:
                if image.width*image.height>40_000_000:raise ValueError('OCR image exceeds 40 megapixels')
                image.thumbnail((2500,2500));pages=[('image',recognize(np.array(image.convert('RGB'))))]
    check()
    if sum(len(t.encode('utf-8')) for _,t in pages)>MAX_TEXT:raise ValueError('Extracted document exceeds 8 MiB')
    if not any(t.strip() for _,t in pages):raise ValueError('No readable text was extracted')
    return pages


def chunks(pages):
    for location,text in pages:
        # Small overlaps retain sentence boundaries without silently losing a
        # document tail. Every chunk is retrievable with its source location.
        text=text.replace('\x00','')
        for start in range(0,len(text),800):
            part=text[start:start+1000].strip()
            if part:yield location,start,part
