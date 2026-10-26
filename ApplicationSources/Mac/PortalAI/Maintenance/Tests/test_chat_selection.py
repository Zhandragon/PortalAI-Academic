"""Last successfully selected chat survives sealing, independently of edit time."""
import json
import unittest
from unittest.mock import Mock, patch
import test_lazy_chat_catalog as fixtures
from native_chat import ChatStore, NativeChat
from profile_paths import ProfileLocked


class ChatSelectionTests(fixtures.LazyChatCatalogTests):
    # Reuse fixture helpers, not the inherited suite.
    def test_selected_older_chat_survives_reopen_without_loading_others(self):
        chat,sessions=self.archive()
        chat.remember_selection(sessions[0]['id'])
        self.runtime.close(self.session,writers_stopped=True)
        self.session=self.backend.login(fixtures.fixtures.OWNER);self.runtime.prepare(self.session)
        chat=ChatStore(self.root)
        self.assertEqual(chat.selected_session(),sessions[0]['id'])
        self.assertEqual(list(chat.sessions.glob('*.json')),[])
        panel=object.__new__(NativeChat);panel.store=chat;panel.session=None
        panel.session_list=Mock();panel._memory_session_label=lambda row:row['title']
        panel.load_session=lambda sid,**kw:chat.load_session(sid)
        panel.refresh_sessions(select_latest=True)
        self.assertEqual([p.stem for p in chat.sessions.glob('*.json')],[sessions[0]['id']])
        self.assertEqual(list(chat.attachments.rglob('*.*')),[])

    def test_deleted_selection_falls_back_to_latest(self):
        chat,sessions=self.archive();chat.remember_selection(sessions[0]['id']);chat.delete_session(sessions[0]['id'])
        panel=object.__new__(NativeChat);panel.store=chat;panel.session=None
        panel.session_list=Mock();panel._memory_session_label=lambda row:row['title'];panel.load_session=Mock()
        panel.refresh_sessions(select_latest=True)
        panel.load_session.assert_called_once_with(sessions[-1]['id'],synchronous=True)

    def test_identical_selection_does_not_rewrite(self):
        chat,sessions=self.archive();chat.remember_selection(sessions[0]['id'])
        with patch('native_chat.write_json',side_effect=AssertionError('Unnecessary write')):
            chat.remember_selection(sessions[0]['id'])

    def test_invalid_selection_is_ignored_without_hydration(self):
        chat,sessions=self.archive()
        for content in ['not json',json.dumps({'version':1,'session_id':'../escape'}),'x'*1025]:
            (chat.base/'selection.json').write_text(content)
            self.assertIsNone(chat.selected_session())
        self.assertEqual(list(chat.sessions.glob('*.json')),[])

    def test_ended_login_cannot_change_selected_chat(self):
        chat,sessions=self.archive();self.runtime.close(self.session,writers_stopped=True)
        with self.assertRaises(ProfileLocked):chat.remember_selection(sessions[0]['id'])

# Do not rerun every fixture test under a second class name.
for _name in tuple(dir(fixtures.LazyChatCatalogTests)):
    if _name.startswith('test_') and _name not in ChatSelectionTests.__dict__:
        setattr(ChatSelectionTests,_name,None)

if __name__=='__main__':unittest.main()
