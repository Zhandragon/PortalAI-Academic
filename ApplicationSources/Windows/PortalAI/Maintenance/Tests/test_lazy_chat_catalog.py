"""Real encrypted disposable histories: no production accounts or inference."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('Agent', 'ControlCenter', 'Maintenance/Tests')]
import test_profile_hydration as fixtures
import profile_hydration as hydration
from profile_workspace import ProfileWorkspace
from native_chat import ChatStore, write_json
from persistent_memory import PersistentMemory
from profile_paths import ProfileLocked, resolve_reference


class LazyChatCatalogTests(unittest.TestCase):
    setUp = fixtures.HydrationTests.setUp
    tearDown = fixtures.HydrationTests.tearDown

    def archive(self):
        chat = ChatStore(self.root)
        sessions = []
        for number in range(3):
            session = chat.new_session()
            session.update(title=f'History {number}', messages=[{'role': 'user', 'content': f'Unique text {number}'}])
            chat.save_session(session); sessions.append(session)
            for folder in ('Attachments', 'Thumbnails', 'Recordings'):
                path = chat.base/folder/session['id']/'fixture.bin'
                path.parent.mkdir(parents=True); path.write_bytes(b'synthetic media'*1000)
        memory = PersistentMemory(self.root)
        for session in sessions:
            state = memory._chat_state(session['id'])
            state.update(capsule='Existing capsule', cursor=1, message_count=1)
        memory.save()
        self.runtime.close(self.session, writers_stopped=True)
        self.session = self.backend.login(fixtures.OWNER)
        self.runtime.prepare(self.session)
        self.store = ProfileWorkspace(self.root, self.session)
        return ChatStore(self.root), sessions

    def test_login_and_list_leave_all_transcripts_and_media_encrypted(self):
        chat, sessions = self.archive()
        self.assertEqual(list(chat.sessions.glob('*.json')), [])
        rows = chat.list_sessions()
        self.assertEqual([r['id'] for r in rows], [s['id'] for s in reversed(sessions)])
        self.assertTrue(all('messages' not in r and r['message_count'] == 1 for r in rows))
        self.assertEqual(list(chat.sessions.glob('*.json')), [])
        with patch.object(chat, '_read_session', side_effect=AssertionError('History reread')):
            for _ in range(20): self.assertEqual(chat.list_sessions(), rows)
        chat.load_session(rows[0]['id'])
        self.assertEqual([p.stem for p in chat.sessions.glob('*.json')], [rows[0]['id']])
        self.assertEqual(list(chat.attachments.rglob('*.bin')), [])

    def test_capsules_toggle_and_clear_use_counts_without_hydrating_sources(self):
        chat, sessions = self.archive()
        memory = PersistentMemory(self.root)
        self.assertEqual(memory.stats()['capsules'], 3)
        sid = sessions[0]['id']
        memory.set_chat_included(sid, False)
        memory.set_chat_included(sid, True)
        memory.clear_for_sessions(chat.list_sessions())
        self.assertTrue(all(memory._chat_state(s['id'])['cursor'] == 1 for s in sessions))
        self.assertEqual(memory.backlog_count(chat.list_sessions()), 0)
        self.assertEqual(list(chat.sessions.glob('*.json')), [])

    def test_distillation_loads_only_one_source_without_media(self):
        chat, sessions = self.archive()
        memory = PersistentMemory(self.root)
        sid = sessions[0]['id']; memory._chat_state(sid)['cursor'] = 0
        with patch.object(memory, 'distill_session', return_value={'updated': True}) as distill:
            memory.maintenance(chat, preferred_sid=sid)
        self.assertEqual(distill.call_args.args[0]['messages'], sessions[0]['messages'])
        self.assertEqual([p.stem for p in chat.sessions.glob('*.json')], [sid])
        self.assertEqual(list(chat.attachments.rglob('*.bin')), [])

    def test_deleting_dormant_chat_survives_seal_without_resurrection(self):
        chat, sessions = self.archive()
        sid = sessions[0]['id']; chat.delete_session(sid)
        self.runtime.close(self.session, writers_stopped=True)
        fresh = self.backend.login(fixtures.OWNER)
        names = {r['path'] for r in ProfileWorkspace(self.root, fresh).verify()['files']}
        self.assertNotIn(f'Data/Chat/Sessions/{sid}.json', names)
        self.assertFalse(any(name.startswith(f'Data/Chat/Attachments/{sid}/') for name in names))
        self.assertIn(f'Data/Chat/Sessions/{sessions[1]["id"]}.json', names)

    def test_stale_catalog_after_interrupted_save_repairs_only_changed_chat(self):
        chat, sessions = self.archive()
        sid = sessions[0]['id']
        row = chat.load_session(sid); row.update(title='After interrupted catalog write')
        write_json(chat.sessions/f'{sid}.json', row)  # Simulate crash before catalog.put.
        self.runtime.close(self.session, writers_stopped=True)
        self.session = self.backend.login(fixtures.OWNER); self.runtime.prepare(self.session)
        self.store = ProfileWorkspace(self.root, self.session)
        chat = ChatStore(self.root)
        rows = chat.list_sessions()
        self.assertEqual(next(r for r in rows if r['id'] == sid)['title'], row['title'])
        self.assertEqual([p.stem for p in chat.sessions.glob('*.json')], [sid])

    def test_old_generation_bootstraps_transcripts_but_never_media(self):
        chat, sessions = self.archive()
        chat.catalog.path.unlink()
        self.runtime.close(self.session, writers_stopped=True)
        self.session = self.backend.login(fixtures.OWNER); self.runtime.prepare(self.session)
        self.store = ProfileWorkspace(self.root, self.session)
        chat = ChatStore(self.root)
        self.assertEqual(len(list(chat.sessions.glob('*.json'))), 3)
        self.assertEqual(len(chat.list_sessions()), 3)
        self.assertTrue(chat.catalog.path.exists())
        self.assertEqual(list(chat.attachments.rglob('*.bin')), [])

    def test_nonhydrating_reference_checks_containment_without_restoring_tree(self):
        chat, sessions = self.archive()
        path = resolve_reference(self.root, 'Outputs', hydrate=False)
        self.assertFalse((path/'old.txt').exists())
        with self.assertRaises((ProfileLocked, ValueError)):
            resolve_reference(self.root, 'Private/Users/'+'f'*32+'/Workspace/Outputs', hydrate=False)

    def test_listing_excludes_materialized_deletions_and_preserves_dormant_names(self):
        chat, sessions = self.archive()
        sid = sessions[0]['id']; chat.load_session(sid)
        (chat.sessions/f'{sid}.json').unlink()
        names = hydration.file_names(self.root, 'Data/Chat/Sessions')
        self.assertEqual(len(names), 2)
        self.assertNotIn(f'Data/Chat/Sessions/{sid}.json', names)
        memory = PersistentMemory(self.root)
        self.assertEqual(memory.stats()['capsules'], 2)

    def test_listing_requires_current_capability_and_pause_rejects_it(self):
        chat, sessions = self.archive()
        self.runtime.pause_hydration()
        with self.assertRaises(ProfileLocked): hydration.file_names(self.root, 'Data/Chat/Sessions')

    def test_actual_child_lists_dormant_chat_names_without_decrypting(self):
        chat, sessions = self.archive()
        script = ('import sys,json; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                  'from profile_hydration import file_names; print(json.dumps(file_names(Path(sys.argv[2]),"Data/Chat/Sessions")))')
        result = subprocess.run([sys.executable, '-B', '-c', script, str(ROOT/'Agent'), str(self.root)],
            env=dict(os.environ), capture_output=True, text=True, timeout=20,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)), 3)
        self.assertEqual(list(chat.sessions.glob('*.json')), [])

    def test_cli_metadata_and_exact_read_preserve_unrelated_dormant_chats(self):
        import memory_tools
        chat, sessions = self.archive()
        self.assertEqual(len(memory_tools.sessions(self.root, metadata=True)), 3)
        self.assertEqual(list(chat.sessions.glob('*.json')), [])
        self.assertEqual(memory_tools.resolve_session(self.root, sessions[0]['id'])['messages'], sessions[0]['messages'])
        self.assertEqual(len(list(chat.sessions.glob('*.json'))), 1)


if __name__ == '__main__': unittest.main()
