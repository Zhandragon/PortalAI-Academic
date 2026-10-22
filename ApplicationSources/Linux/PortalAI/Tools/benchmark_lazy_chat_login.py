"""Bounded synthetic login benchmark on the portable volume; no live accounts."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/p) for p in ('Agent', 'ControlCenter', 'Tools')]
from validation_artifacts import ValidationArtifacts
from local_accounts import LocalAccounts
from profile_workspace import ProfileWorkspace
from profile_runtime import ProfileRuntime
from chat_catalog import summary, fingerprint
from native_chat import ChatStore


def run(destination):
    with tempfile.TemporaryDirectory(prefix='login-fixture-', dir=destination) as folder, patch.dict(os.environ):
        root = Path(folder).resolve()
        if not root.is_relative_to(destination): raise ValueError('Disposable root required')
        for key in list(os.environ):
            if key.startswith('PORTALAI_PROFILE_') or key.startswith('PORTALAI_HYDRATION_'): os.environ.pop(key)
        backend = LocalAccounts(root); secret = 'Synthetic-only-lazy-login-2026'
        session = backend.bootstrap('Benchmark', secret)
        store = ProfileWorkspace(root, session); catalog = {}
        for n in range(60):
            sid = f'chat-{n:04}'
            row = {'id': sid, 'title': f'Synthetic chat {n}', 'created': n, 'updated': n,
                   'messages': [{'role': 'user', 'content': 'Synthetic chat content. '*80}]}
            path = store.workspace/f'Data/Chat/Sessions/{sid}.json'
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(row), encoding='utf-8')
            catalog[sid] = {**summary(row), '_sha256': fingerprint(path)}
            for tree in ('Attachments', 'Thumbnails', 'Recordings'):
                media = store.workspace/f'Data/Chat/{tree}/{sid}/synthetic.bin'
                media.parent.mkdir(parents=True, exist_ok=True); media.write_bytes(b'x'*65536)
        (store.workspace/'Data/Chat/session_catalog.json').write_text(json.dumps({'version': 1, 'sessions': catalog}), encoding='utf-8')
        store.seal(writers_stopped=True); backend.logout(session)
        results = []
        # Alternating order; each case restores the same encrypted fixture.
        for lazy in (False, True, True, False):
            session = backend.login('Benchmark', secret)
            runtime = ProfileRuntime(root, backend, lazy_restore=lazy,
                quiesce=Mock(return_value={'stopped': True}), legacy_check=lambda _root: {'clean': True})
            try:
                started = time.perf_counter(); runtime.prepare(session)
                login_seconds = time.perf_counter()-started
                store = ProfileWorkspace(root, session)
                before = store.inventory()
                started = time.perf_counter(); chat = ChatStore(root); rows = chat.list_sessions(); chat.load_session(rows[0]['id'])
                open_seconds = time.perf_counter()-started
                pending = store.pending()
                assert len(rows) == 60
                if lazy:
                    assert len(list(chat.sessions.glob('*.json'))) == 1
                    assert not list(chat.attachments.rglob('*.bin'))
                result = {'lazy': lazy, 'login_seconds': round(login_seconds, 4),
                          'list_and_latest_seconds': round(open_seconds, 4),
                          'initial_plaintext_files': len(before), 'initial_plaintext_bytes': sum(r['bytes'] for r in before),
                          'pending_after_latest': pending['files']}
                results.append(result); print(json.dumps(result), flush=True)
            finally:
                runtime.close(session, writers_stopped=True)
        return {'passed': True, 'scope': 'Synthetic warm-cache 60 chats and 180 small media files; not a production speed guarantee',
                'production_accounts_opened': False, 'results': results}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--artifacts-dir', required=True)
    args = parser.parse_args(); artifacts = ValidationArtifacts(ROOT, args.artifacts_dir)
    report = run(artifacts.path())
    artifacts.path('benchmark.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
