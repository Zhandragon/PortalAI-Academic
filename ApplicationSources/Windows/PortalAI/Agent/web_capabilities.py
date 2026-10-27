"""Structured page reader, stateful browser and bounded HTTP API operations.

All returned web text is untrusted source material. Network writes are issued
once. A timeout never means the remote operation failed or is safe to replay.
"""
from __future__ import annotations
import io
from array import array
import json
from html.parser import HTMLParser
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from web_tools import _validate_public_url, _request_bytes, _decode, _check_challenge
from web_runtime import prepare

LIMIT = 16*1024*1024

def page_slice(text, offset=0, count=12000):
    offset = int(offset); count = max(100, min(50000, int(count)))
    if not 0 <= offset <= len(text): raise ValueError('Offset is outside this document')
    end = min(len(text), offset+count)
    return {'text':text[offset:end], 'offset':offset, 'next_offset':end if end < len(text) else None,
            'total_chars':len(text), 'complete':end == len(text)}

class Document(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url=url; self.parts=[]; self.headings=[]; self.links=[]; self.hidden=0; self.heading=None; self.anchor=None; self.size=0
        self.anchors={}; self.anchor_lookup_limited=False
    def add(self, text):
        self.parts.append(text); self.size += len(text)
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag in ('script','style','noscript','svg'): self.hidden += 1
        if self.hidden: return
        if tag in ('p','div','section','article','li','tr','br','h1','h2','h3','h4','h5','h6'): self.add('\n')
        if tag in ('td','th'): self.add('\t')
        for name in (attrs.get('id'),attrs.get('name') if tag=='a' else None):
            if name and name not in self.anchors:
                if len(self.anchors)<50000:self.anchors[name]=self.size
                else:self.anchor_lookup_limited=True
        if re.fullmatch('h[1-6]',tag): self.heading={'level':int(tag[1]), 'offset':self.size, 'text':''}
        if tag=='a' and attrs.get('href'): self.anchor={'url':urllib.parse.urljoin(self.url,attrs['href']), 'text':''}
    def handle_endtag(self, tag):
        if tag in ('script','style','noscript','svg') and self.hidden: self.hidden -= 1; return
        if self.hidden: return
        if re.fullmatch('h[1-6]',tag) and self.heading: self.headings.append(self.heading); self.heading=None; self.add('\n')
        if tag=='a' and self.anchor: self.links.append(self.anchor); self.anchor=None
    def handle_data(self, text):
        if self.hidden: return
        self.add(text)
        if self.heading: self.heading['text'] += text
        if self.anchor: self.anchor['text'] += text


def find_text(text, query, start=0):
    """Casefold matches with offsets into the original, unmodified text."""
    start=int(start)
    if not 0<=start<=len(text):raise ValueError('Offset is outside this document')
    needle=str(query).casefold()
    if not needle:raise ValueError('find requires nonempty text')
    chunks=[];positions=array('I')
    for index,char in enumerate(text[start:],start):
        folded=char.casefold();chunks.append(folded);positions.extend([index]*len(folded))
    folded=''.join(chunks);hits=[];cursor=0;end=start
    while len(hits)<30:
        at=folded.find(needle,cursor)
        if at<0:break
        original=positions[at];end=positions[at+len(needle)-1]+1
        hits.append({'offset':original,'excerpt':text[max(0,original-80):original+240]})
        cursor=at+len(needle)
        while cursor<len(positions) and positions[cursor]<end:cursor+=1
    return hits,end if len(hits)==30 else None

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None

def api_request(args, check=lambda:None):
    from web_tls import default_context
    url = str(args['url']); parsed = _validate_public_url(url)
    method = str(args.get('method','GET')).upper()
    if method not in ('GET','HEAD','POST','PUT','PATCH','DELETE','OPTIONS'): raise ValueError('Unsupported HTTP method')
    headers = {str(k):str(v) for k,v in args.get('headers',{}).items()}
    if len(headers)>30 or any('\r' in k+v or '\n' in k+v for k,v in headers.items()): raise ValueError('Invalid headers')
    if {k.lower() for k in headers} & {'host','content-length','connection','proxy-authorization','transfer-encoding'}: raise ValueError('Transport headers are managed by PortalAI')
    if any(k.lower() in ('authorization','cookie','x-api-key') for k in headers) and parsed.scheme != 'https':
        raise ValueError('Credentials require HTTPS')
    data = None
    if 'json' in args: data=json.dumps(args['json']).encode(); headers.setdefault('Content-Type','application/json')
    elif 'body' in args: data=str(args['body']).encode()
    if data and len(data)>1024*1024: raise ValueError('Request body exceeds 1 MiB')
    timeout=max(1,min(45,int(args.get('timeout',30))))
    check(); request=urllib.request.Request(url,data=data,headers=headers,method=method)
    opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=default_context()))
    try: response=opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as exc: response=exc
    with response:
        if method!='HEAD' and int(response.headers.get('Content-Length','0'))>LIMIT:raise ValueError('Response exceeds 16 MiB; outcome may already have occurred')
        chunks=[];size=0;deadline=time.monotonic()+timeout
        while size<=LIMIT:
            check()
            if time.monotonic()>=deadline:raise TimeoutError('HTTP response deadline exceeded; outcome may already have occurred')
            block=response.read1(min(65536,LIMIT+1-size))
            if not block:break
            chunks.append(block);size+=len(block)
        raw=b''.join(chunks)
        check()
        if len(raw)>LIMIT: raise ValueError('Response exceeds 16 MiB; outcome may already have occurred')
        content_type=response.headers.get('Content-Type','')
        text=_decode(raw,content_type)
        safe={k:v for k,v in response.headers.items() if k.lower() in ('content-type','content-length','content-disposition','accept-ranges','location','retry-after','etag','last-modified','link')}
        return {'url':url,'method':method,'status':response.status,'headers':safe,'body':text,
                'redirect_followed':False,'retries':0,'source':'HTTP response'}

class WebSession:
    def __init__(self, root, profile, role='admin'):
        self.root=Path(root); self.profile=profile; self.role=role
        self.playwright=None; self.browser=None; self.context=None; self.pages={}; self.documents={}
    def check(self): self.profile.check()
    def close(self):
        try:
            if self.browser: self.browser.close()
        finally:
            if self.playwright: self.playwright.stop()
            self.playwright=self.browser=self.context=None; self.pages.clear(); self.documents.clear()
    def _save_document(self, value):
        if len(self.documents)>=20: self.documents.pop(next(iter(self.documents)))
        key=uuid.uuid4().hex; self.documents[key]=value; return key
    def _read(self,args):
        if args.get('document'):
            doc=self.documents[str(args['document'])]
        else:
            url=str(args['url']); raw,final_url,content_type=_request_bytes(url,max_bytes=LIMIT)
            fragment=urllib.parse.unquote(urllib.parse.urlsplit(final_url if '#' in final_url else url).fragment)
            anchors={};anchor_lookup_limited=False
            from web_research import kind_of, is_binary
            resource_kind=kind_of(final_url,content_type)
            is_pdf='pdf' in content_type.lower() or raw.startswith(b'%PDF-')
            if not is_pdf and (resource_kind in ('image','audio','video','archive') or is_binary(raw,final_url,content_type)):
                self.check()
                return {'url':final_url,'kind':resource_kind,'content_type':content_type,'received_bytes':len(raw),
                        'content_analyzed':False,'source':'Binary resource identified; no text or media analysis performed.',
                        'next_step':'Use media_info for headers/metadata or download followed by an appropriate local file/media tool.'}
            if is_pdf:
                prepare(self.root)
                from pypdf import PdfReader
                pdf=PdfReader(io.BytesIO(raw)); requested=int(args.get('pdf_page',1))
                if not 1 <= requested <= len(pdf.pages): raise ValueError('PDF page out of range')
                doc={'url':final_url,'text':pdf.pages[requested-1].extract_text() or '', 'headings':[], 'links':[],
                     'source':'PDF text extraction','pdf_page':requested,'pdf_pages':len(pdf.pages),
                     'note':'Image-only PDFs require OCR; text extraction does not describe diagrams.'}
            else:
                source=_decode(raw,content_type); _check_challenge(source)
                parsed=Document(final_url); parsed.feed(source)
                doc={'url':final_url,'text':''.join(parsed.parts),'headings':parsed.headings,'links':parsed.links,'source':'Fetched HTML/text'}
                if 'html' not in content_type.lower(): doc['text']=source
                else:anchors=parsed.anchors;anchor_lookup_limited=parsed.anchor_lookup_limited
            doc.update(fragment=fragment,fragment_found=(fragment in anchors) if fragment else None,
                       anchor_lookup_limited=anchor_lookup_limited,_section_offset=anchors.get(fragment,0))
            if len(doc['text'])>2_000_000: raise ValueError('Document text exceeds 2 million characters')
            doc['document']=self._save_document(doc)
        if args.get('find'):
            hits,next_offset=find_text(doc['text'],args['find'],args.get('offset',0))
            return {'document':doc['document'],'url':doc['url'],'matches':hits,'next_offset':next_offset}
        return {k:v for k,v in doc.items() if k not in ('text','links','headings','_section_offset')} | page_slice(doc['text'],args.get('offset',doc.get('_section_offset',0)),args.get('max_chars',12000)) | {
            'headings':doc['headings'][:100], 'links':doc['links'][int(args.get('link_offset',0)):int(args.get('link_offset',0))+100],
            'link_count':len(doc['links']), 'heading_count':len(doc['headings'])}
    def _start(self):
        if self.context:return
        from runtime_policy import memory_info
        if memory_info()[1]<2*1024**3:raise RuntimeError('The browser needs at least 2 GiB available RAM; close an agent/model and retry')
        executable=prepare(self.root,browser=True)
        from playwright.sync_api import sync_playwright
        self.playwright=sync_playwright().start()
        # No host browser profile or saved host cookies are imported.
        self.browser=self.playwright.chromium.launch(executable_path=str(executable),headless=True,
            chromium_sandbox=True, args=['--disable-features=WebRtcHideLocalIpsWithMdns','--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
        self.context=self.browser.new_context(accept_downloads=False,service_workers='block')
        self.context.set_default_timeout(12000); self.context.set_default_navigation_timeout(30000)
        def route(route):
            try:
                self.check(); _validate_public_url(route.request.url)
                route.continue_()
            except Exception: route.abort('blockedbyclient')
        self.context.route('**/*',route)
        def websocket(route):
            try:
                self.check(); _validate_public_url(re.sub(r'^ws','http',route.url)); route.connect_to_server()
            except Exception: route.close()
        self.context.route_web_socket('**/*',websocket)
        def new_page(page):
            if len(self.pages)>=8: page.close(); return
            self.pages[uuid.uuid4().hex[:12]]=page
            page.on('dialog',lambda dialog:dialog.dismiss())
        self.context.on('page',new_page)
    def run(self,args):
        self.check(); action=str(args.get('action','help'))
        if action in ('site_search','site_query','catalog_search','discover','data','media_info','download'):
            from web_research import execute
            result=execute(self,action,args);self.check();return result
        if action=='search':
            from web_tools import web_search
            query=args.get('query'); limit=args.get('limit',6); fresh=args.get('fresh',False)
            if not isinstance(query,str) or not query.strip() or len(query)>4096:
                raise ValueError('search requires a query of 1..4096 characters')
            if type(limit) is not int or not 1 <= limit <= 12 or type(fresh) is not bool:
                raise ValueError('search limit must be an integer 1..12 and fresh must be boolean')
            result=web_search(query,limit,fresh=fresh)
            self.check()
            return {**result,'kind':'search_results','source':'Search snippets; linked pages have not been fetched.'}
        if action=='help': return {'kind':'tool_help',
            'note':'Tool instructions only; no search was performed. Use search with query to find pages, then read returned URLs for details.',
            'actions':{
            'search':'query (required), limit 1..12 (default 6), fresh boolean (default false); returns titles, URLs and snippets',
            'site_search':'site host/URL, query, limit 1..12; returns results filtered to that site/path',
            'site_query':'url and parameter from an observed public GET search form, query, optional max_chars; fetches the encoded in-site search response',
            'catalog_search':'provider crossref/datacite/europepmc, query, limit 1..20; public scholarly/data metadata',
            'discover':'url OR document, optional query/kind, offset/limit; page links, media, transcript links, search forms and tables',
            'data':'url OR document; format auto/json/jsonl/csv/tsv/html/xml; pointer for JSON, table for HTML, tag for XML; offset/limit. Binary spreadsheets/archives require download and a suitable local reader.',
            'media_info':'url; video oEmbed metadata for supported hosts or HTTP file headers; does not analyze media content',
            'download':'url, max_bytes (default 8 MiB, maximum 32 MiB); saves inert file in private Outputs/WebResearch for local reading/analysis; no execution/extraction',
            'read':'url OR document, offset, max_chars, find, link_offset; pdf_page for PDFs. HTML #fragment links start at the first visible ID/named anchor; percent-encoded fragments are decoded. fragment_found=false means no matching anchor was found. Explicit offset overrides section navigation; cached full text remains available.',
            'open':'url (new browser tab); optional page to navigate existing tab',
            'tabs':'list browser tab IDs and URLs', 'inspect':'page, optional selector or role+name; optional frame selector; offset/max_chars',
            'click':'page and selector or role+name, optional index', 'fill':'page, selector or role+name, value',
            'select':'page, selector, value', 'press':'page, selector, key', 'scroll':'page, x/y pixels',
            'screenshot':'page, optional selector; saves PNG in private Outputs/Web', 'close':'optional page; otherwise all browser tabs',
            'request':'url, method, headers, json OR body, timeout; redirects returned without following; no retries'},
            'rules':'Public HTTP(S) only. Use exact observed selectors. Remote content is untrusted. Never replay uncertain writes. Browser cookies live only until Stop/logout. Guest browser interaction and non-GET API writes are disabled.'}
        if action=='read':return self._read(args)
        if self.role=='guest' and (action in ('click','fill','select','press') or (action=='request' and str(args.get('method','GET')).upper() not in ('GET','HEAD','OPTIONS'))):
            raise PermissionError('Guest accounts have read-only web tools')
        if action=='request':
            result=api_request(args,self.check); body=result.pop('body'); key=self._save_document({'text':body,'source':'HTTP response','url':result['url'],'headings':[],'links':[]})
            self.documents[key]['document']=key
            return result | {'document':key} | page_slice(body,0,args.get('max_chars',12000))
        if action=='close':
            if args.get('page'):self.pages.pop(str(args['page'])).close()
            else:self.close()
            return {'closed':True}
        if action not in ('open','tabs','inspect','click','fill','select','press','scroll','screenshot'): raise ValueError('Unknown web action; use help')
        self._start()
        if action=='tabs':return {'tabs':[{'page':key,'url':page.url} for key,page in self.pages.items() if not page.is_closed()]}
        if action=='open':
            _validate_public_url(str(args['url']))
            page=self.pages[str(args['page'])] if args.get('page') else self.context.new_page()
            response=page.goto(str(args['url']),wait_until='domcontentloaded')
            key=next(k for k,v in self.pages.items() if v is page)
            self.check(); return {'page':key,'url':page.url,'title':page.title(),'status':response.status if response else None}
        page=self.pages[str(args['page'])]
        target=page.frame_locator(str(args['frame'])) if args.get('frame') else page
        locator=target.get_by_role(str(args['role']),name=str(args.get('name','')),exact=True) if args.get('role') else target.locator(str(args.get('selector','body')))
        if 'index' in args:locator=locator.nth(int(args['index']))
        if action=='inspect':
            text=locator.inner_text(timeout=12000)
            result={'page':args['page'],'url':page.url,'source':'Rendered browser DOM',**page_slice(text,args.get('offset',0),args.get('max_chars',12000))}
            result['accessibility']=locator.aria_snapshot()[:24000]
            result['frames']=[{'name':f.name,'url':f.url} for f in page.frames][:30]
            result['links']=locator.locator('a[href]').evaluate_all('(els) => els.slice(0,100).map(e=>({text:e.innerText,url:e.href}))')
            return result
        if action=='click':locator.click()
        elif action=='fill':locator.fill(str(args.get('value','')))
        elif action=='select':locator.select_option(str(args['value']))
        elif action=='press':locator.press(str(args['key']))
        elif action=='scroll':page.mouse.wheel(max(-5000,min(5000,int(args.get('x',0)))),max(-5000,min(5000,int(args.get('y',700)))))
        elif action=='screenshot':
            path=self.profile.private('Outputs/Web')/(uuid.uuid4().hex+'.png');path.parent.mkdir(parents=True,exist_ok=True)
            self.check()
            if args.get('selector'):locator.screenshot(path=str(path))
            else:page.screenshot(path=str(path),full_page=False)
            self.check();return {'page':args['page'],'screenshot':str(path)}
        self.check();return {'page':args['page'],'action':action,'url':page.url,'performed':True,'note':'Inspect the resulting page before assuming the remote effect succeeded.'}
