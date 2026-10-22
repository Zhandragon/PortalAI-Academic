"""Bounded progress evidence for a mission; never an execution checkpoint."""
import json
import os
import time

from runtime_policy import atomic_json


class Activity:
    def __init__(self, store, mission):
        self.store=store;self.mid=mission['id'];self.last_write=0
        self.value={'mission':self.mid,'pid':os.getpid(),'started_at':time.time(),
                    'phase':'queued','message':'Waiting for a worker','generated_chars':0,'preview':'','events':[]}
        previous=read(store,self.mid)
        self.value['events']=previous.get('events',[])[-79:]

    def update(self, phase, message, *, preview=None, generated_chars=None, force=False):
        now=time.time();changed=phase!=self.value['phase'] or message!=self.value['message']
        self.value.update(phase=phase,message=str(message)[:1000],updated_at=now)
        if preview is not None:self.value['preview']=str(preview)[-8000:]
        if generated_chars is not None:self.value['generated_chars']=generated_chars
        if changed:
            self.value['events']=(self.value['events']+[{'at':now,'phase':phase,'message':str(message)[:1000]}])[-80:]
        if changed or force or now-self.last_write>=.3:
            path=self.store.folder(self.mid)/'activity.json'
            try:atomic_json(path,self.value)
            except OSError as exc:
                self.store.folder(self.mid)  # Never swallow an ended login.
                self.value['recording_error']=str(exc)
            self.last_write=now


def read(store, mid):
    path=store.folder(mid)/'activity.json'
    try:
        if not path.exists():return {}
        if path.stat().st_size>256*1024:raise ValueError('Activity record is too large; mission checkpoints are preserved.')
        value=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value,dict) or value.get('mission')!=mid:raise ValueError('Invalid activity identity')
        if not isinstance(value.get('events',[]),list) or any(not isinstance(row,dict) for row in value.get('events',[])):
            raise ValueError('Invalid activity timeline; mission checkpoints are preserved.')
        for key in ('started_at','updated_at','generated_chars','pid'):
            if key in value and not isinstance(value[key],(int,float)):raise ValueError('Invalid activity '+key)
        for key in ('phase','message','preview'):
            if key in value and not isinstance(value[key],str):raise ValueError('Invalid activity '+key)
        return value
    except (ValueError,OSError) as exc:return {'error':str(exc)}
