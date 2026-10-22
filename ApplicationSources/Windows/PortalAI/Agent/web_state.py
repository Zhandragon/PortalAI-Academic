"""Small portable search cache and provider cooldowns; no credentials stored."""
import sys as _profile_sys
from pathlib import Path as _ProfilePath
_profile_agent_dir = str(_ProfilePath(__file__).resolve().parent)
if _profile_agent_dir not in _profile_sys.path:
    _profile_sys.path.insert(0, _profile_agent_dir)
from profile_paths import capture, private_path, ProfileLocked, _contained
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from types import MappingProxyType

from runtime_policy import ROOT, require_space


class WebState:
    def __init__(self, root=ROOT, *, environ=None):
        self.root=Path(root).resolve()
        # Explicit environments are only for isolated, unprofiled test roots.
        # Production deliberately observes the live environment on every check.
        self._environ=None if environ is None else MappingProxyType(dict(environ))
        self.context=capture(self.root, environ=self._environ)
        if self._environ is not None and self.context is not None:
            raise ValueError('An explicit web-cache environment requires an unprofiled fixture root')
        self.path=self._path()
        self.check()

    def _path(self):
        if self._environ is not None:
            return _contained(self.root, self.root/'Cache/Web/search.sqlite3')
        return private_path(self.root, 'Cache/Web/search.sqlite3', context=self.context)

    def check(self):
        if capture(self.root, environ=self._environ) != self.context:
            raise ProfileLocked('The web request login ended')
        # Revalidate containment as well as the epoch: a stored Path must not
        # recreate an old workspace, or follow a later replacement junction.
        current=self._path()
        if current != self.path:
            raise ProfileLocked('The web cache no longer belongs to this login')

    @contextmanager
    def connection(self):
        self.check()
        require_space(self.root,16*1024**2,for_outputs=True)
        self.check()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.check()
        db=sqlite3.connect(self.path,timeout=3)
        try:
            self.check()
            db.execute('PRAGMA max_page_count=2048')
            db.execute('CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, at REAL, value TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS cooldown (provider TEXT PRIMARY KEY, until REAL, reason TEXT)')
            yield db
            # The context manager owns the transaction. In particular, a
            # revoked save/block must roll back rather than commit on db exit.
            self.check()
            db.commit()
            self.check()
        except BaseException:
            db.rollback()
            raise
        finally:db.close()

    @staticmethod
    def key(query,limit):
        return hashlib.sha256(json.dumps([query,limit],ensure_ascii=False).encode('utf-8')).hexdigest()

    def cached(self,query,limit):
        self.check()
        if not self.path.exists():return None
        with self.connection() as db:
            row=db.execute('SELECT at,value FROM cache WHERE key=?',(self.key(query,limit),)).fetchone()
        if not row or not 0<=time.time()-row[0]<=300:return None
        value=json.loads(row[1])
        self.check()
        return {**value,'cached':True,'cache_age_seconds':round(time.time()-row[0],1)}

    def save(self,query,limit,value):
        self.check()
        # Queries are hashed. Store only returned public result metadata.
        raw=json.dumps({'provider':value['provider'],'results':value['results']},ensure_ascii=False)
        if len(raw.encode('utf-8'))>64000:return
        with self.connection() as db:
            self.check()
            db.execute('INSERT OR REPLACE INTO cache VALUES (?,?,?)',(self.key(query,limit),time.time(),raw))
            db.execute('DELETE FROM cache WHERE at<?',(time.time()-300,))
            db.execute('DELETE FROM cache WHERE key NOT IN (SELECT key FROM cache ORDER BY at DESC LIMIT 64)')

    def cooling(self,provider):
        self.check()
        if not self.path.exists():return None
        with self.connection() as db:
            row=db.execute('SELECT until,reason FROM cooldown WHERE provider=?',(provider,)).fetchone()
        if row and row[0]>time.time():
            return {'provider':provider,'category':'cooldown','retry_after_seconds':int(row[0]-time.time())+1,'message':row[1]}
        return None

    def block(self,provider,seconds,reason):
        self.check()
        with self.connection() as db:
            self.check()
            db.execute('INSERT OR REPLACE INTO cooldown VALUES (?,?,?)',(provider,time.time()+max(1,min(86400,seconds)),reason))
            db.execute('DELETE FROM cooldown WHERE until<?',(time.time(),))
            db.execute('DELETE FROM cooldown WHERE provider NOT IN (SELECT provider FROM cooldown ORDER BY until DESC LIMIT 128)')
