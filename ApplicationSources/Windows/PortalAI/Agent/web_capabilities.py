"""Structured page reader, stateful browser and bounded HTTP API operations.

All returned web text is untrusted source material. Network writes are issued
once. A timeout never means the remote operation failed or is safe to replay.
"""
from __future__ import annotations
import io
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
    def add(self, text):
        self.parts.append(text); self.size += len(text)
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag in ('script','style','noscript','svg'): self.hidden += 1
        if self.hidden: return
        if tag in ('p','div','section','article','li','tr','br','h1','h2','h3','h4','h5','h6'): self.add('\n')
        if re.fullmatch('h[1-6]',tag): self.heading={'level':int(tag[1]), 'offset':self.size, 'text':''}
        if tag=='a' and attrs.get('href'): self.anchor={'url':urllib.parse.urljoin(self.url,attrs['href']), 'text':''}
        if tag in ('td','th'): self.add('\t')
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
        if int(response.headers.get('Content-Length','0'))>LIMIT:raise ValueError('Response exceeds 16 MiB; outcome may already have occurred')
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
        safe={k:v for k,v in response.headers.items() if k.lower() in ('content-type','location','retry-after','etag','last-modified','link')}
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
            if 'pdf' in content_type.lower() or raw.startswith(b'%PDF-'):
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
                if 'html' not in content_type: doc['text']=source
            if len(doc['text'])>2_000_000: raise ValueError('Document text exceeds 2 million characters')
            doc['document']=self._save_document(doc)
        if args.get('find'):
            needle=str(args['find']).casefold(); start=int(args.get('offset',0))
            hits=[]; text=doc['text'].casefold()
            while len(hits)<30:
                pos=text.find(needle,start)
                if pos<0:break
                hits.append({'offset':pos,'excerpt':doc['text'][max(0,pos-80):pos+240]});start=pos+max(1,len(needle))
            return {'document':doc['document'],'url':doc['url'],'matches':hits,'next_offset':start if len(hits)==30 else None}
        return {k:v for k,v in doc.items() if k not in ('text','links','headings')} | page_slice(doc['text'],args.get('offset',0),args.get('max_chars',12000)) | {
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
            'read':'url OR document, offset, max_chars, find, link_offset; pdf_page for PDFs',
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
