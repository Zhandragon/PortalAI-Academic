"""Owned local GUI read-state client; no outbound HA transport or credentials.

The outbound receiver transport validates its explicit native.state.read grant
before using this module. Projection image/input polling cannot confer that grant.
"""
import http.client
import json
import os
from pathlib import Path
import re
import uuid

PROTOCOL='portalai-native-state/2'
MAX_FRAME=180000


class NativeStateClient:
    def __init__(self, manager):
        self.manager=manager; self.binding=None; self.endpoint=None
        self.owned_row=None
        self.generation=uuid.uuid4().hex

    def discover(self):
        from portalai_target import gui_row
        manager=self.manager
        if manager.endpoint_dir is None: raise RuntimeError('native_scope_unavailable')
        folder=Path(manager.endpoint_dir)
        for part in (folder,*folder.parents):
            if part.is_symlink() or getattr(part,'is_junction',lambda:False)(): raise RuntimeError('linked_scope')
        # Bind with a fresh argv/root inventory. Once bound, the kernel-checked
        # creation time and executable below pin that same process, so repeated
        # reads do not run a slow machine-wide inventory. Never trust PID alone.
        if self.endpoint is None:
            owned={pid:row for pid,row in manager.inventory(True).items() if gui_row(manager.root,row)}
        else:
            if self.owned_row is None: raise RuntimeError('native_bind_required')
            owned={self.endpoint['pid']:self.owned_row}
        if len(owned)!=1: raise RuntimeError('single_owned_GUI_required')
        pid,row=next(iter(owned.items())); path=folder/('native-gui-'+str(pid)+'.json')
        if path.is_symlink() or not path.is_file() or path.stat().st_size>4096 or path.stat().st_nlink!=1:
            raise RuntimeError('native_GUI_restart_required')
        endpoint=json.loads(path.read_text(encoding='utf-8'))
        if set(endpoint)!={'version','protocol','scope','pid','start','hwnd','port','token'}:
            raise RuntimeError('native_endpoint_fields')
        divisor=10 if os.name=='nt' else 1
        if (endpoint['version']!=2 or endpoint['protocol']!=PROTOCOL or endpoint['scope']!='native.state.read'
            or endpoint['pid']!=pid or type(endpoint['start']) is not int or endpoint['start']//divisor!=row['start']//divisor
            or type(endpoint['hwnd']) is not int or type(endpoint['port']) is not int or not 1024<=endpoint['port']<=65535
            or not isinstance(endpoint['token'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',endpoint['token'])):
            raise RuntimeError('native_endpoint_identity')
        windows=manager.desktop.windows(owned)
        window=next((w for w in windows if w['hwnd']==endpoint['hwnd'] and w['pid']==pid),None)
        if window is None: raise RuntimeError('native_window_not_owned')
        manager.desktop.validate({**window,'executable':row['executable']})
        self.owned_row=dict(row)
        return endpoint

    def request(self, path, body):
        endpoint=self.discover()  # Reverify process creation/window identity on every read.
        if self.endpoint is not None and endpoint!=self.endpoint:
            self.binding=None; raise RuntimeError('native_GUI_changed_rebind_required')
        conn=http.client.HTTPConnection('127.0.0.1',endpoint['port'],timeout=2)
        try:
            conn.request('POST',path,json.dumps(body).encode('utf-8'),
                         {'Authorization':'Bearer '+endpoint['token'],'Content-Type':'application/json'})
            response=conn.getresponse(); raw=response.read(MAX_FRAME+1)
            if response.status!=200 or len(raw)>MAX_FRAME or response.getheader('Content-Encoding'):
                self.binding=None; raise RuntimeError('native_state_unavailable_or_revoked')
            def pairs(items):
                result={}
                for k,v in items:
                    if k in result: raise ValueError('duplicate_key')
                    result[k]=v
                return result
            def invalid(_): raise ValueError('nonfinite')
            value=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=invalid)
            if not isinstance(value,dict) or value.get('protocol')!=PROTOCOL or value.get('generation')!=self.generation:
                raise RuntimeError('native_protocol')
            return endpoint,value
        finally: conn.close()

    def bind(self, *, fresh=False):
        self.endpoint=None; self.binding=None; self.owned_row=None; self.generation=uuid.uuid4().hex
        endpoint,value=self.request('/native/v2/rebind' if fresh else '/native/v2/bind',{'protocol':PROTOCOL,'generation':self.generation})
        if set(value)!={'protocol','generation','binding','capabilities','maxFrameBytes','leaseMs'} or value['capabilities']!=['native.state.read'] or value['maxFrameBytes']!=MAX_FRAME or value['leaseMs']!=2000:
            raise RuntimeError('native_handshake')
        binding=value['binding']
        if not isinstance(binding,dict) or set(binding)!={'view','epoch'} or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{32}',v) for v in binding.values()):
            raise RuntimeError('native_binding')
        self.endpoint=endpoint; self.binding=binding
        return value

    def snapshot(self):
        if self.binding is None: raise RuntimeError('native_bind_required')
        _,value=self.request('/native/v2/snapshot',{'protocol':PROTOCOL,'generation':self.generation,**self.binding})
        if set(value)!={'protocol','generation','kind','snapshot'} or value['kind']!='snapshot': raise RuntimeError('native_envelope')
        s=value['snapshot']
        if not isinstance(s,dict) or any(s.get(k)!=v for k,v in self.binding.items()):
            self.binding=None; raise RuntimeError('native_binding_changed')
        # The receiver must independently validate the full v2 snapshot schema.
        return value
