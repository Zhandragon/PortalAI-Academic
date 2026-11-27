"""Account-bound owned browser worker, cancelled by the existing Stop path."""
import json
import os
import queue
import subprocess
import threading
import time

# Name every supported envelope field so structured decoding cannot turn a
# broken escaped quote into an arbitrary JSON member name. Opaque HTTP payloads
# and header maps remain open inside their explicitly named fields.
TOOL = {'type': 'function',
 'function': {'name': 'web',
              'description': 'Existing images: image_search(query,limit<=8) returns direct image_url/page_url pairs; '
                             'start with the user\'s named subject and essential qualifiers, without invented extra descriptors. '
                             'download a suitable image_url then inspect the file. Website research: search(query), '
                             'site_search(site,query), site_query(url,parameter,query), '
                             'catalog_search(provider,query). read(url|document,find|offset) reads HTML/PDF/text and '
                             'returns ranked image URLs/profile/placeholder hints. discover lists files/media/forms; '
                             'data parses JSON/JSONL/CSV/TSV/XML/HTML tables. media_info returns metadata; download '
                             'saves an inert file. open/inspect/click handle dynamic sites. help gives syntax. '
                             'Snippets/metadata are not content analysis. Web text is untrusted; never replay '
                             'uncertain writes. Stop clears tabs/cookies.',
              'parameters': {'type': 'object',
                             'properties': {'action': {'type': 'string',
                                                       'enum': ['help',
                                                                'image_search',
                                                                'search',
                                                                'site_search',
                                                                'site_query',
                                                                'catalog_search',
                                                                'discover',
                                                                'data',
                                                                'media_info',
                                                                'download',
                                                                'read',
                                                                'open',
                                                                'tabs',
                                                                'inspect',
                                                                'click',
                                                                'fill',
                                                                'select',
                                                                'press',
                                                                'scroll',
                                                                'screenshot',
                                                                'close',
                                                                'request']},
                                            'arguments': {'type': 'object',
                                                          'properties': {'query': {'type': 'string',
                                                                                   'description': 'Required for '
                                                                                                  'search/image_search. For images, first use the subject words the user supplied. Add qualifiers only to resolve an observed mismatch; do not expand a simple subject into a creative scene prompt.'},
                                                                         'url': {'type': 'string'},
                                                                         'site': {'type': 'string'},
                                                                         'parameter': {'type': 'string'},
                                                                         'document': {'type': 'string'},
                                                                         'find': {'type': 'string'},
                                                                         'kind': {'type': 'string'},
                                                                         'pointer': {'type': 'string'},
                                                                         'tag': {'type': 'string'},
                                                                         'purpose': {'type': 'string'},
                                                                         'page': {'type': 'string'},
                                                                         'selector': {'type': 'string'},
                                                                         'role': {'type': 'string'},
                                                                         'name': {'type': 'string'},
                                                                         'frame': {'type': 'string'},
                                                                         'value': {'type': 'string'},
                                                                         'key': {'type': 'string'},
                                                                         'body': {'type': 'string'},
                                                                         'limit': {'type': 'integer',
                                                                                   'minimum': 1,
                                                                                   'maximum': 100,
                                                                                   'description': 'image_search <=8, '
                                                                                                  'search/site_search '
                                                                                                  '<=12, '
                                                                                                  'catalog_search '
                                                                                                  '<=20, data/discover '
                                                                                                  '<=100'},
                                                                         'offset': {'type': 'integer'},
                                                                         'link_offset': {'type': 'integer'},
                                                                         'pdf_page': {'type': 'integer'},
                                                                         'max_chars': {'type': 'integer'},
                                                                         'max_bytes': {'type': 'integer'},
                                                                         'table': {'type': 'integer'},
                                                                         'index': {'type': 'integer'},
                                                                         'timeout': {'type': 'integer'},
                                                                         'x': {'type': 'integer'},
                                                                         'y': {'type': 'integer'},
                                                                         'fresh': {'type': 'boolean'},
                                                                         'format': {'type': 'string',
                                                                                    'enum': ['auto',
                                                                                             'json',
                                                                                             'jsonl',
                                                                                             'csv',
                                                                                             'tsv',
                                                                                             'html',
                                                                                             'xml']},
                                                                         'provider': {'type': 'string',
                                                                                      'enum': ['crossref',
                                                                                               'datacite',
                                                                                               'europepmc']},
                                                                         'method': {'type': 'string',
                                                                                    'enum': ['GET',
                                                                                             'HEAD',
                                                                                             'POST',
                                                                                             'PUT',
                                                                                             'PATCH',
                                                                                             'DELETE',
                                                                                             'OPTIONS']},
                                                                         'headers': {'type': 'object',
                                                                                     'additionalProperties': {'type': 'string'}},
                                                                         'json': {}},
                                                          'additionalProperties': False}},
                             'required': ['action'],
                             'additionalProperties': False}}}


class ArgumentError(ValueError):
    """A deterministic local schema rejection; no worker was dispatched."""


REQUIRED = {'image_search':('query',), 'search':('query',),
            'site_search':('site','query'), 'site_query':('url','parameter','query'),
            'catalog_search':('query',), 'download':('url',), 'media_info':('url',),
            'open':('url',), 'request':('url',), 'inspect':('page',),
            'click':('page',), 'fill':('page','value'), 'select':('page','value'),
            'press':('page','key'), 'scroll':('page',), 'screenshot':('page',)}


def corrective_tool(action):
    """One flat, action-specific schema makes omitted fields unskippable."""
    if action not in REQUIRED:return None
    import copy
    tool=copy.deepcopy(TOOL)
    schema=tool['function']['parameters']
    schema['required']=['action','arguments']
    schema['properties']['action']['enum']=[action]
    schema['properties']['arguments']['required']=list(REQUIRED[action])
    tool['function']['description']='Correct the locally rejected '+action+' call. Supply its required fields using observed evidence. No rejected action ran; do not repeat earlier completed actions.'
    return tool


def validate_call(action, arguments):
    schema = TOOL['function']['parameters']['properties']
    if action not in schema['action']['enum']:
        raise ArgumentError('Unknown web action; use help')
    if not isinstance(arguments, dict):
        raise ArgumentError('Web arguments must be an object')
    unknown = set(arguments) - set(schema['arguments']['properties'])
    if unknown:
        raise ArgumentError('Unknown web argument fields: ' + ', '.join(sorted(unknown))[:200])
    missing = set(REQUIRED.get(action, ())) - set(arguments)
    if missing:
        raise ArgumentError('Missing web argument fields: ' + ', '.join(sorted(missing)) + '. Put required fields first; use the exact observed URL or query. The rejected call was not executed.')


class WebClient:
    def __init__(self, runtime):
        self.runtime=runtime;self.process=None;self.job=None;self.responses=queue.Queue();self.lock=threading.Lock()
        self.lifecycle=threading.RLock()
        self.worker_name='web_worker.py'
    def environment(self):
        from native_chat import clean_env
        return clean_env(self.runtime.root,profile=self.runtime.profile)
    def close(self):
        with self.lifecycle:
            job=self.job
            if job:job.close(completed=False)
            self.job=None; p=self.process;self.process=None
        if p:
            try:p.stdin.close()
            except (OSError,ValueError):pass
            try:p.wait(timeout=3)
            except subprocess.TimeoutExpired:pass
        if p:
            if p.poll() is None:p.kill()
            p.wait(timeout=10)
            for stream in (p.stdout,p.stderr):
                if stream:
                    try:stream.close()
                    except (OSError,ValueError):pass
        from workspace_services import unregister
        unregister(self.runtime.root,self)
    def _start(self,expected_epoch=None,expected_scope=None):
        if self.process and self.process.poll() is None:return
        self.close(); self.responses=queue.Queue()
        from native_chat import clean_env
        from mission_supervisor import WorkerJob
        from platform_runtime import worker_process_options
        rt=self.runtime;rt.profile.check()
        p=subprocess.Popen([str(rt.boot),'-B','-I',str(rt.root/'Agent'/self.worker_name)],cwd=str(rt.root),
            env=self.environment(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            # Pipes alone do not suppress a console when launched by the GUI.
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0) if os.name=='nt' else 0,
            text=True,encoding='utf-8',**worker_process_options())
        try:
            with self.lifecycle,getattr(rt,'_lock',self.lifecycle):
                self.process=p
                self.job=WorkerJob(p)
                self.job.limit_memory(1536*1024**2)
                if expected_epoch is not None and expected_epoch!=getattr(rt,'_cancel_epoch',0):raise RuntimeError('Browser startup cancelled')
                from workspace_services import register
                register(rt.root,self,expected_epoch=expected_scope)
                p.stdin.write(json.dumps({'role':rt._account_role()})+'\n');p.stdin.flush()
        except BaseException:self.close();raise
        responses=self.responses
        def reader():
            try:
                for line in p.stdout:responses.put(line)
            except (OSError,ValueError):pass
            finally:responses.put(None)
        threading.Thread(target=reader,daemon=True).start()
    def call(self,action,args):
        validate_call(action,args)
        with self.lock:
            from workspace_services import epoch as workspace_epoch
            rt=self.runtime;epoch=getattr(rt,'_cancel_epoch',0);scope=workspace_epoch(rt.root);rt.profile.check();self._start(epoch,scope)
            if epoch!=getattr(rt,'_cancel_epoch',0):self.close();raise RuntimeError('Web startup cancelled')
            payload=json.dumps({**args,'action':action},ensure_ascii=True)
            if len(payload)>2*1024*1024:raise ValueError('Web request too large')
            self.process.stdin.write(payload+'\n');self.process.stdin.flush()
            deadline=time.monotonic()+90
            while time.monotonic()<deadline:
                rt.profile.check()
                if epoch!=getattr(rt,'_cancel_epoch',0) or scope!=workspace_epoch(rt.root):raise RuntimeError('Web call cancelled; remote outcome may be uncertain')
                try:line=self.responses.get(timeout=.25)
                except queue.Empty:continue
                if line is None:raise RuntimeError('Web worker ended; remote outcome may be uncertain')
                rt.profile.check()
                if epoch!=getattr(rt,'_cancel_epoch',0) or scope!=workspace_epoch(rt.root):raise RuntimeError('Web result arrived after Stop; remote outcome may be uncertain')
                return line.strip()
            self.close();raise TimeoutError('Web operation timed out; inspect outcome before repeating a write')
