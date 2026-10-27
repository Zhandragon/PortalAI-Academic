"""Bounded public research, data previews and inert file/media discovery.

Returned content is evidence, never instructions. Downloads are explicit, scoped
to the active profile and never opened, executed or extracted by this module.
"""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import re
from html.parser import HTMLParser
from urllib.parse import quote, urlencode, urljoin, urlsplit, parse_qsl, urlunsplit
import uuid
import xml.etree.ElementTree as ET

from web_tools import _candidate_url, _request_bytes, _decode, _check_challenge, web_search, require_space
from profile_paths import _contained

MAX_BYTES = 2 * 1024 * 1024
KINDS = {
    'image': ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.avif'),
    'video': ('.mp4', '.webm', '.mov', '.mkv', '.m3u8', '.mpd'),
    'audio': ('.mp3', '.wav', '.ogg', '.flac', '.m4a', '.aac'),
    'pdf': ('.pdf',), 'data': ('.json', '.jsonl', '.csv', '.tsv', '.xml', '.parquet', '.xlsx', '.xls'),
    'feed': ('.rss', '.atom'), 'transcript': ('.vtt', '.srt'),
    'archive': ('.zip', '.gz', '.tar', '.7z'), 'text': ('.txt', '.md', '.py', '.r', '.sql'),
}


def integer(args, name, default, low, high):
    value = args.get(name, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{name} must be an integer {low}..{high}')
    return value


def kind_of(url, content_type=''):
    content_type = content_type.lower().split(';')[0]
    for prefix in ('image', 'audio', 'video'):
        if content_type.startswith(prefix + '/'):
            return prefix
    if content_type == 'application/pdf': return 'pdf'
    if content_type in ('application/rss+xml', 'application/atom+xml'): return 'feed'
    if content_type in ('text/vtt', 'application/x-subrip'): return 'transcript'
    if content_type in ('application/json', 'text/csv', 'text/tab-separated-values', 'application/xml'): return 'data'
    path = urlsplit(url).path.lower()
    for kind, suffixes in KINDS.items():
        if path.endswith(suffixes): return kind
    return 'page' if not content_type or 'html' in content_type else 'file'


def public_link(base, target):
    url = urljoin(base, str(target))
    _candidate_url(url)
    return url


class Resources(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url = url; self.links = []; self.seen = set(); self.current = None
        self.title = ''; self.in_title = False; self.hidden = 0; self.media = []
        self.forms = []; self.form = None; self.tables = []; self.table = None; self.row = None; self.cell = None
        self.json_ld = None; self.json_ld_size = 0
        self.feed_link = None
        self.truncated = False

    def add_link(self, target, label='', mime='', kind=None, source='link'):
        if not target: return
        if len(self.links) >= 2000: self.truncated=True;return
        try: url = public_link(self.url, target)
        except (ValueError, TypeError): return
        identity = (url, kind or kind_of(url, mime))
        if identity in self.seen: return
        self.seen.add(identity)
        item = {'url':url, 'label':str(label)[:500], 'kind':identity[1], 'content_type_hint':mime[:150],
                'source':source, 'content_fetched':False}
        self.links.append(item)
        return item

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('type','').lower() == 'application/ld+json':
            self.json_ld = []; self.json_ld_size = 0
        if tag in ('script','style','noscript','template','svg'): self.hidden += 1
        if self.hidden: return
        if tag == 'title': self.in_title = True
        if tag == 'a': self.current = self.add_link(attrs.get('href'),attrs.get('title',''),attrs.get('type',''),source='a')
        if tag in ('video','audio'):
            self.media.append(tag); self.add_link(attrs.get('src'),mime=attrs.get('type',''),kind=tag,source=tag)
            self.add_link(attrs.get('poster'),kind='image',source='poster')
        if tag == 'source': self.add_link(attrs.get('src'),mime=attrs.get('type',''),kind=self.media[-1] if self.media else None,source='source')
        if tag == 'track': self.add_link(attrs.get('src'),attrs.get('label',''),kind='transcript',source='track')
        if tag == 'img': self.add_link(attrs.get('src'),attrs.get('alt',''),kind='image',source='img')
        if tag == 'iframe': self.add_link(attrs.get('src'),attrs.get('title',''),kind='embedded_page',source='iframe')
        if tag == 'link':
            rel = attrs.get('rel','').lower().split()
            if 'alternate' in rel or 'search' in rel:
                self.add_link(attrs.get('href'),attrs.get('title',''),attrs.get('type',''),source='alternate' if 'alternate' in rel else 'search_description')
            elif not attrs.get('href'): self.feed_link=[]
        if tag in ('enclosure','media:content'):
            self.add_link(attrs.get('url'),mime=attrs.get('type',''),source=tag)
        if tag == 'meta':
            name = attrs.get('property',attrs.get('name','')).lower()
            for prefix in ('image','audio','video'):
                if name in ('og:'+prefix,'og:'+prefix+':url','og:'+prefix+':secure_url'):
                    self.add_link(attrs.get('content'),kind=prefix,source=name)
        if tag == 'form' and attrs.get('method','get').lower() == 'get' and len(self.forms) < 12:
            try: action = public_link(self.url,attrs.get('action',self.url))
            except ValueError: return
            self.form = {'action':action,'method':'GET','fields':[],'submitted':False};self.forms.append(self.form)
        if tag == 'input' and self.form is not None and len(self.form['fields'])<40 and attrs.get('type','text') in ('text','search') and attrs.get('name'):
            self.form['fields'].append({'name':attrs['name'][:100],'label':attrs.get('aria-label',attrs.get('placeholder',''))[:200]})
        if tag == 'table' and len(self.tables)<10: self.table=[];self.tables.append(self.table)
        if tag == 'tr' and self.table is not None and len(self.table)>=1000:self.truncated=True
        if tag == 'tr' and self.table is not None and len(self.table)<1000: self.row=[];self.table.append(self.row)
        if tag in ('td','th') and self.row is not None and len(self.row)<50: self.cell=[]

    def handle_endtag(self,tag):
        if tag == 'script' and self.json_ld is not None:
            try: self.structured_links(json.loads(''.join(self.json_ld)))
            except (ValueError,TypeError,RecursionError): pass
            self.json_ld=None
        if tag in ('script','style','noscript','template','svg') and self.hidden:
            self.hidden-=1;return
        if self.hidden: return
        if tag == 'link' and self.feed_link is not None:
            self.add_link(''.join(self.feed_link).strip(),source='feed_link');self.feed_link=None
        if tag == 'title': self.in_title=False
        if tag == 'a': self.current=None
        if tag in ('video','audio') and self.media: self.media.pop()
        if tag == 'form': self.form=None
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split())[:1000]);self.cell=None
        if tag == 'tr': self.row=None;self.cell=None
        if tag == 'table': self.table=None;self.row=None;self.cell=None

    def handle_data(self,text):
        if self.json_ld is not None and self.json_ld_size < 200000:
            self.json_ld.append(text[:200000-self.json_ld_size]);self.json_ld_size+=len(text)
        if self.hidden:return
        if self.feed_link is not None:self.feed_link.append(text[:8192])
        if self.in_title:self.title+=text[:max(0,1000-len(self.title))]
        if self.current:self.current['label']=(self.current['label']+text)[:500]
        if self.cell is not None and sum(map(len,self.cell))<1000:self.cell.append(text[:1000])

    def structured_links(self,value,depth=0):
        if depth>12:return
        if isinstance(value,list):
            for item in value[:100]:self.structured_links(item,depth+1)
        if isinstance(value,dict):
            type_name=str(value.get('@type',''));kind={'VideoObject':'video','AudioObject':'audio','ImageObject':'image','Dataset':'data'}.get(type_name)
            for key in ('contentUrl','embedUrl','thumbnailUrl','downloadUrl'):
                if isinstance(value.get(key),str):self.add_link(value[key],value.get('name',''),str(value.get('encodingFormat','')),kind='image' if key=='thumbnailUrl' else kind,source='json_ld:'+key)
            for item in list(value.values())[:100]:
                if isinstance(item,(dict,list)):self.structured_links(item,depth+1)


def fetch_document(session,args):
    session.check()
    if args.get('document'):
        doc=session.documents[str(args['document'])]
        if 'text' not in doc:raise ValueError('Document has no readable text')
        return doc
    url=args.get('url')
    if not isinstance(url,str):raise ValueError('url or document is required')
    raw,final,mime=_request_bytes(url,max_bytes=MAX_BYTES)
    session.check()
    if raw.startswith(b'%PDF-') or 'pdf' in mime.lower():raise ValueError('Use read with pdf_page for PDFs')
    if kind_of(final,mime) in ('image','video','audio','archive') or is_binary(raw,final,mime):
        raise ValueError('Binary media needs media_info or download, then a supported local analysis tool')
    text=_decode(raw,mime);_check_challenge(text)
    doc={'url':final,'text':text,'content_type':mime,'source':'Fetched resource','headings':[],'links':[]}
    doc['document']=session._save_document(doc);session.check()
    return doc


def discover(session,args):
    doc=fetch_document(session,args);offset=integer(args,'offset',0,0,2000);limit=integer(args,'limit',30,1,100)
    parser=Resources(doc['url']);parser.feed(doc['text'])
    links=parser.links;query=args.get('query','');kind=args.get('kind')
    if not isinstance(query,str) or len(query)>500:raise ValueError('query must be text up to 500 characters')
    if query:links=[x for x in links if query.casefold() in (x['label']+' '+x['url']).casefold()]
    if kind:links=[x for x in links if x['kind']==kind]
    session.check()
    return {'kind':'resource_discovery','url':doc['url'],'document':doc['document'],'offset':offset,'query':query,'resource_kind':kind,'title':' '.join(parser.title.split()),'resources':links[offset:offset+limit],
            'total_resources':len(links),'next_offset':offset+limit if offset+limit<len(links) else None,
            'search_forms':parser.forms,'tables_found':len(parser.tables),
            'bounded_preview':True,'scan_truncated':parser.truncated,'parse_limits':{'links':2000,'tables':10,'rows_per_table':1000,'columns':50,'search_fields':40},
            'source':'Page links/metadata only; linked media and files have not been fetched or analyzed.'}


def site_search(session,args):
    site=args.get('site');query=args.get('query');limit=integer(args,'limit',6,1,12)
    if not isinstance(site,str) or not site.strip() or len(site)>2048:raise ValueError('site must be a public host or URL')
    parsed=_candidate_url(site if '://' in site else 'https://'+site)
    if parsed.query or parsed.fragment:raise ValueError('site must be a host or path without query/fragment')
    if not isinstance(query,str) or not query.strip() or len(query)>2048:raise ValueError('query is required')
    host=parsed.hostname.lower();prefix=parsed.path.rstrip('/')
    fresh=args.get('fresh',False)
    if type(fresh) is not bool:raise ValueError('fresh must be boolean')
    session.check();result=web_search('site:'+host+prefix+' '+query,12,fresh=fresh);session.check()
    selected=[]
    for row in result['results']:
        target=urlsplit(row['url']);target_host=(target.hostname or '').lower()
        if (target_host==host or target_host.endswith('.'+host)) and (not prefix or target.path==prefix or target.path.startswith(prefix+'/')):
            selected.append(row)
    return {**result,'site':host+prefix,'results':selected[:limit],'kind':'search_results',
            'scope_filter_applied':True,'source':'Search snippets restricted to the requested site; pages have not been fetched.'}


def is_binary(raw,url,mime):
    return (raw.startswith((b'PK\x03\x04',b'PAR1',b'\x1f\x8b',b'\xd0\xcf\x11\xe0'))
            or b'\x00' in raw[:2048] and not raw.startswith((b'\xff\xfe',b'\xfe\xff'))
            or urlsplit(url).path.lower().endswith(('.xlsx','.xls','.parquet','.docx','.pptx')))


def site_query(session,args):
    """Submit a discovered public GET search endpoint, with encoded parameters."""
    parsed=_candidate_url(args.get('url'))
    parameter=args.get('parameter');query=args.get('query')
    if not isinstance(parameter,str) or not re.fullmatch(r'[A-Za-z_][A-Za-z_0-9.\[\]-]{0,99}',parameter):
        raise ValueError('parameter must be an observed search field name')
    if not isinstance(query,str) or not 1<=len(query)<=2000:raise ValueError('query must contain 1..2000 characters')
    pairs=[(k,v) for k,v in parse_qsl(parsed.query,keep_blank_values=True,max_num_fields=50) if k!=parameter]
    target=urlunsplit((parsed.scheme,parsed.netloc,parsed.path,urlencode(pairs+[(parameter,query)]),''))
    session.check()
    result=session._read({'url':target,'max_chars':integer(args,'max_chars',12000,100,50000)})
    session.check()
    return {**result,'search_endpoint':target,'query':query,'parameter':parameter,
            'search_note':'Fetched the public GET search response. Relevance and pagination must be checked from the returned page; use browser tools if results require JavaScript.'}


def short_value(value,depth=0):
    if depth>5:return {'truncated':True,'type':type(value).__name__}
    if isinstance(value,str):return value[:1000]+('…' if len(value)>1000 else '')
    if isinstance(value,list):return [short_value(x,depth+1) for x in value[:30]]
    if isinstance(value,dict):return {str(k)[:200]:short_value(v,depth+1) for k,v in list(value.items())[:30]}
    return value


def read_data(session,args):
    doc=fetch_document(session,args);text=doc['text'];mime=doc.get('content_type','').lower()
    offset=integer(args,'offset',0,0,10000);limit=integer(args,'limit',20,1,100);fmt=args.get('format','auto')
    if fmt=='auto':
        if 'ndjson' in mime or urlsplit(doc['url']).path.lower().endswith(('.jsonl','.ndjson')):fmt='jsonl'
        elif 'json' in mime or text.lstrip().startswith(('{','[')):fmt='json'
        elif 'html' in mime or re.search(r'<(?:html|table)\b',text[:2000],re.I):fmt='html'
        elif 'xml' in mime or text.lstrip().startswith('<'):fmt='xml'
        elif 'tab-separated' in mime or urlsplit(doc['url']).path.lower().endswith('.tsv'):fmt='tsv'
        else:fmt='csv'
    metadata={};items=None
    if fmt=='json':
        value=json.loads(text);pointer=args.get('pointer','')
        if not isinstance(pointer,str) or (pointer and not pointer.startswith('/')) or len(pointer)>2048:raise ValueError('pointer must be an RFC 6901 JSON pointer')
        for part in pointer.split('/')[1:]:
            if re.search(r'~(?![01])',part):raise ValueError('Invalid JSON pointer escape')
            part=part.replace('~1','/').replace('~0','~')
            if isinstance(value,list):
                if not re.fullmatch(r'0|[1-9][0-9]*',part):raise ValueError('Invalid JSON pointer array index')
                value=value[int(part)]
            elif isinstance(value,dict):value=value[part]
            else:raise ValueError('JSON pointer cannot traverse a scalar')
        items=value if isinstance(value,list) else [{'key':k,'value':v} for k,v in value.items()] if isinstance(value,dict) else [value]
        metadata={'pointer':pointer,'value_type':type(value).__name__}
    elif fmt=='jsonl':
        items=[]
        for number,line in enumerate(text.splitlines(),1):
            if not line.strip():continue
            if len(items)>=20000:raise ValueError('JSONL exceeds 20,000 records')
            try:items.append(json.loads(line))
            except ValueError as exc:raise ValueError('Invalid JSONL record at line '+str(number)) from exc
    elif fmt in ('csv','tsv'):
        reader=csv.reader(io.StringIO(text),delimiter='\t' if fmt=='tsv' else ',');items=[]
        for row in reader:
            if len(items)>=20000:raise ValueError('Table exceeds 20,000 rows; use a smaller server-side query')
            items.append(row[:100])
        metadata={'header':items[0] if items else [],'header_is_first_row':True}
    elif fmt=='html':
        parser=Resources(doc['url']);parser.feed(text);index=integer(args,'table',0,0,9)
        if index>=len(parser.tables):raise ValueError('Requested table not found; use discover to inspect available resources')
        items=parser.tables[index];metadata={'table':index,'tables_found':len(parser.tables),'header':items[0] if items else [],'scan_truncated':parser.truncated,'max_rows_per_table':1000}
    elif fmt=='xml':
        if re.search(r'<!\s*(DOCTYPE|ENTITY)\b',text,re.I):raise ValueError('XML document types and entities are not supported')
        root=ET.fromstring(text);nodes=list(root.iter())
        if len(nodes)>20000:raise ValueError('XML exceeds 20,000 elements')
        tag=args.get('tag')
        if tag is not None and (not isinstance(tag,str) or len(tag)>200):raise ValueError('tag must be a short element name')
        chosen=[node for node in nodes if node.tag.rsplit('}',1)[-1]==tag] if tag else list(root)
        items=[{'tag':n.tag.rsplit('}',1)[-1],'attributes':dict(n.attrib),'text':''.join(n.itertext())[:4000],
                'children':[{'tag':child.tag.rsplit('}',1)[-1],'attributes':dict(child.attrib),'text':''.join(child.itertext())[:1000]} for child in list(n)[:40]]} for n in chosen]
        metadata={'root_tag':root.tag,'tag':tag}
    else:raise ValueError('format must be auto, json, jsonl, csv, tsv, html or xml')
    session.check()
    return {'kind':'data_preview','document':doc['document'],'url':doc['url'],'format':fmt,**short_value(metadata),'items':[short_value(item) for item in items[offset:offset+limit]],
            'offset':offset,'total_items':len(items),'next_offset':offset+limit if offset+limit<len(items) and offset+limit<=10000 else None,
            'more_available':offset+limit<len(items),'maximum_preview_offset':10000,
            'source':'Bounded parsed-data preview; cell/nested values may be shortened. Use read for exact text.'}


def catalog_search(session,args):
    provider=args.get('provider','crossref');query=args.get('query');limit=integer(args,'limit',5,1,20)
    if not isinstance(query,str) or not 1<=len(query)<=2000:raise ValueError('query must contain 1..2000 characters')
    endpoints={
        'crossref':('https://api.crossref.org/works',{'query':query,'rows':limit}),
        'datacite':('https://api.datacite.org/dois',{'query':query,'page[size]':limit}),
        'europepmc':('https://www.ebi.ac.uk/europepmc/webservices/rest/search',{'query':query,'pageSize':limit,'format':'json'}),
    }
    if provider not in endpoints:raise ValueError('provider must be crossref, datacite or europepmc')
    endpoint,params=endpoints[provider];url=endpoint+'?'+urlencode(params)
    session.check();raw,final,mime=_request_bytes(url,max_bytes=MAX_BYTES,headers={'Accept':'application/json'});session.check()
    payload=json.loads(_decode(raw,mime));rows=[]
    if provider=='crossref':
        total=payload['message'].get('total-results')
        for r in payload['message'].get('items',[])[:limit]:rows.append({'title':' '.join(r.get('title',[])),'url':r.get('URL'),'identifier':r.get('DOI'),'type':r.get('type'),'links':r.get('link',[])[:5]})
    elif provider=='datacite':
        total=payload.get('meta',{}).get('total')
        for record in payload.get('data',[])[:limit]:
            r=record.get('attributes',{});rows.append({'title':' '.join(t.get('title','') for t in r.get('titles',[])),'url':r.get('url') or 'https://doi.org/'+str(r.get('doi','')),'identifier':r.get('doi'),'type':r.get('types',{}).get('resourceTypeGeneral')})
    else:
        total=payload.get('hitCount')
        for r in payload.get('resultList',{}).get('result',[])[:limit]:rows.append({'title':r.get('title'),'url':'https://europepmc.org/article/'+quote(str(r.get('source','MED')),safe='')+'/'+quote(str(r.get('id','')),safe=''),'identifier':r.get('doi') or r.get('id'),'open_access':r.get('isOpenAccess')=='Y','type':'article'})
    cleaned=[]
    for row in rows:
        try:_candidate_url(row['url'])
        except (ValueError,TypeError):continue
        links=[]
        for link in row.get('links',[]):
            try:_candidate_url(link.get('URL',''));links.append(link)
            except (ValueError,TypeError):pass
        if 'links' in row:row['links']=links
        cleaned.append(short_value(row))
    session.check()
    return {'kind':'catalog_results','provider':provider,'query':query,'url':final,'total_results':total,'results':cleaned,
            'source':'Public database metadata; records, papers and files have not been fetched.'}


def media_info(session,args):
    from web_capabilities import api_request
    url=args.get('url');parsed=_candidate_url(url);session.check()
    if parsed.hostname in ('youtube.com','www.youtube.com','youtu.be','vimeo.com','www.vimeo.com'):
        endpoint='https://www.youtube.com/oembed' if 'youtu' in parsed.hostname else 'https://vimeo.com/api/oembed.json'
        raw,final,mime=_request_bytes(endpoint+'?'+urlencode({'url':url,'format':'json'}),max_bytes=256000)
        value=json.loads(_decode(raw,mime));session.check()
        return {'url':url,'kind':'video','metadata':{k:value[k] for k in ('title','author_name','author_url','provider_name','thumbnail_url','duration','width','height') if k in value},
                'content_analyzed':False,'source':'Public oEmbed metadata only; no video or transcript was read.'}
    result=api_request({'url':url,'method':'HEAD'},session.check);session.check()
    return {**result,'kind':kind_of(url,result['headers'].get('Content-Type',result['headers'].get('content-type',''))),
            'content_analyzed':False,'source':'HTTP headers only; use discover for page media/transcript links, read for text, or download for local analysis.'}


def download(session,args):
    if session.role=='guest':raise PermissionError('Guest cannot save downloaded files')
    limit=integer(args,'max_bytes',8*1024*1024,1,32*1024*1024);url=args.get('url');_candidate_url(url)
    session.check();raw,final,mime=_request_bytes(url,max_bytes=limit);session.check()
    if 'html' in mime.lower():_check_challenge(_decode(raw[:30000],mime))
    kind=kind_of(final,mime);ext=Path(urlsplit(final).path).suffix.lower()
    allowed={suffix for values in KINDS.values() for suffix in values}|{'.html'}
    if ext not in allowed:ext={"application/pdf":".pdf","application/json":".json","text/csv":".csv","text/plain":".txt","text/html":".html","video/mp4":".mp4","audio/mpeg":".mp3"}.get(mime.split(';')[0].lower(),'.data')
    folder=session.profile.private('Outputs/WebResearch');_contained(session.root,folder)
    require_space(session.root,len(raw)+1024**2,for_outputs=True);session.check();folder.mkdir(parents=True,exist_ok=True)
    path=folder/(uuid.uuid4().hex+ext);part=path.with_suffix(ext+'.part');identity=None;published=False
    try:
        _contained(session.root,part);session.check()
        with part.open('xb') as stream:
            stat=os.fstat(stream.fileno());identity=(stat.st_dev,stat.st_ino)
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        session.check();_contained(session.root,path)
        if path.exists():raise FileExistsError('Download destination already exists')
        part.rename(path);published=True;session.check()
        return {'path':str(path),'files':[str(path)],'url':final,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),
                'content_type':mime,'kind':kind,'content_analyzed':False,'executed':False,
                'next_step':'Use a supported local file reader; media_tool transcribe accepts audio/video and video-understand accepts video. Fetch tool help before selecting arguments. Downloading does not verify content or meaning.'}
    except BaseException:
        if published:
            _contained(session.root,path)
            if path.is_file() and not path.is_symlink():
                stat=path.lstat()
                if (stat.st_dev,stat.st_ino)==identity:path.unlink()
        raise
    finally:
        _contained(session.root,part)
        if part.is_file() and not part.is_symlink():
            stat=part.lstat()
            if (stat.st_dev,stat.st_ino)==identity:part.unlink()


def execute(session,action,args):
    operations={'site_search':site_search,'site_query':site_query,'catalog_search':catalog_search,'discover':discover,'data':read_data,'media_info':media_info,'download':download}
    return operations[action](session,args)
