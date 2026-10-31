"""Selection/confirmation safety and encrypted disposable batch deletion."""
import sys,threading,unittest
from pathlib import Path
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
from native_chat import NativeChat,ChatStore
from persistent_memory import PersistentMemory
from profile_paths import ProfileLocked
import test_lazy_chat_catalog as fixtures


class SelectionDeleteTests(unittest.TestCase):
    def panel(self):
        p=NativeChat.__new__(NativeChat)
        p.busy=False;p._closing=False;p.app=Mock();p.session={'id':'c','title':'Keep open'}
        p.store=Mock();p.memory=Mock();p._check_login=Mock();p._confirm=Mock();p._notice=Mock()
        p.session_order=['a','b','c'];p.session_list=Mock();p.session_list.curselection.return_value=(0,1)
        p.store.list_sessions.return_value=[{'id':'a','title':'First chat'},{'id':'b','title':'Second chat'},p.session]
        p.pending_attachments=['draft'];p.release_audio_capture=Mock();p.render_history=Mock()
        p.refresh_sessions_labels_only=Mock();p._update_memory_chat_button=Mock();p.load_session=Mock()
        return p

    def confirm(self,p):
        p.delete_chat();return p._confirm.call_args.args[2]

    def test_full_preview_and_exact_snapshot_preserve_unselected_open_chat(self):
        p=self.panel();perform=self.confirm(p)
        self.assertEqual(p._confirm.call_args.kwargs['items'],('1. First chat','2. Second chat'))
        self.assertEqual(p._confirm.call_args.kwargs['yes_text'],'Delete 2 chats')
        p.store.delete_session.assert_not_called()
        p.session_list.curselection.return_value=(2,) # Confirmation keeps its original IDs.
        perform();perform()
        self.assertEqual([c.args[0] for c in p.store.delete_session.call_args_list],['a','b'])
        self.assertEqual([c.args[0] for c in p.memory.forget_chat.call_args_list],['a','b'])
        self.assertEqual(p.session['id'],'c');self.assertEqual(p.pending_attachments,['draft'])
        p.load_session.assert_not_called();p.release_audio_capture.assert_not_called()

    def test_cancel_does_not_delete_or_cancel_other_work(self):
        p=self.panel();self.confirm(p)
        p.store.delete_session.assert_not_called();p.memory.cancel_active.assert_not_called()

    def test_single_selected_chat_wins_over_previously_open_chat(self):
        p=self.panel();p.session_list.curselection.return_value=(1,)
        self.confirm(p)();p.store.delete_session.assert_called_once_with('b')

    def test_empty_filtered_selection_never_deletes_hidden_open_chat(self):
        p=self.panel();p.session_list.curselection.return_value=()
        p.delete_chat();p._confirm.assert_not_called();p.store.delete_session.assert_not_called()

    def test_filtered_order_is_the_source_of_selected_ids(self):
        p=self.panel();p.session_order=['b','a'];p.session_list.curselection.return_value=(0,)
        self.confirm(p)();p.store.delete_session.assert_called_once_with('b')

    def test_preview_does_not_load_transcripts_and_includes_every_title(self):
        p=self.panel();p.session_order=[str(i) for i in range(150)]
        p.session_list.curselection.return_value=tuple(range(150))
        p.store.list_sessions.return_value=[{'id':str(i),'title':f'Synthetic {i}'} for i in range(150)]
        self.confirm(p);self.assertEqual(len(p._confirm.call_args.kwargs['items']),150)
        self.assertEqual(p._confirm.call_args.kwargs['items'][-1],'150. Synthetic 149')
        p.store.load_session.assert_not_called()

    def test_stale_catalog_selection_refuses(self):
        p=self.panel();p.store.list_sessions.return_value=[];p.delete_chat()
        p._confirm.assert_not_called();p._notice.assert_called_once()

    def test_busy_closing_or_changed_account_refuse_delayed_confirmation(self):
        for change in ('busy','closing','store','memory'):
            p=self.panel();perform=self.confirm(p);store=p.store
            if change=='busy':p.busy=True
            elif change=='closing':p._closing=True
            else:setattr(p,change,Mock())
            perform();store.delete_session.assert_not_called()

    def test_revoked_login_refuses_confirmation(self):
        p=self.panel();perform=self.confirm(p);p._check_login.side_effect=ProfileLocked('Ended login')
        with self.assertRaises(ProfileLocked):perform()
        p.store.delete_session.assert_not_called()

    def test_stop_invalidates_confirmation(self):
        p=self.panel();perform=self.confirm(p);p.stop_generation();perform()
        p.store.delete_session.assert_not_called()

    def test_pending_reads_and_search_cannot_publish_deleted_sessions(self):
        p=self.panel();p._session_load_after='timer'
        reads=[{'cancel':threading.Event()} for _ in range(2)]
        p._session_load_request,p._history_search_request=reads
        self.confirm(p)()
        self.assertTrue(all(r['cancel'].is_set() for r in reads))
        p.app.after_cancel.assert_called_once_with('timer')
        self.assertIsNone(p._session_load_request);self.assertIsNone(p._history_search_request)

    def test_partial_failure_stops_batch_and_reports_count(self):
        p=self.panel();p.store.delete_session.side_effect=[None,OSError('Synthetic unavailable disk')]
        self.confirm(p)()
        self.assertEqual(p.store.delete_session.call_count,2)
        p.memory.forget_chat.assert_called_once_with('a')
        self.assertIn('Removed 1 of 2',p._notice.call_args.args[1])
        p.refresh_sessions_labels_only.assert_called_once()

    def test_deleting_open_chat_selects_survivor_and_clears_old_display(self):
        p=self.panel();p.session={'id':'a'};p.store.list_sessions.side_effect=[
            [{'id':'a'},{'id':'b'},{'id':'c'}],[{'id':'c'}]]
        self.confirm(p)()
        p.release_audio_capture.assert_called_once();p.render_history.assert_called_once()
        self.assertEqual(p.pending_attachments,[]);p.load_session.assert_called_once_with('c',synchronous=True)

    def test_deleting_all_creates_one_new_chat(self):
        p=self.panel();p.session={'id':'a'}
        p.store.list_sessions.side_effect=[[{'id':'a'},{'id':'b'}],[]]
        p.store.new_session.return_value={'id':'new'}
        self.confirm(p)();p.store.new_session.assert_called_once()
        p.load_session.assert_called_once_with('new',synchronous=True)

    def test_context_menu_enables_bulk_delete(self):
        p=self.panel();p.COL={'panel':'#fff','text':'#000','cyan':'#00f'}
        p.session_list.nearest.return_value=0
        with patch('native_chat.tk.Menu') as factory:
            p._history_context_menu(Mock(y=1,x_root=1,y_root=1))
            actions=[call.kwargs for call in factory.return_value.add_command.call_args_list]
        delete=next(row for row in actions if row['label']=='Delete selected…')
        self.assertNotEqual(delete.get('state'),'disabled');self.assertEqual(delete['command'],p.delete_chat)


class EncryptedDeleteTests(unittest.TestCase):
    setUp=fixtures.LazyChatCatalogTests.setUp
    tearDown=fixtures.LazyChatCatalogTests.tearDown
    archive=fixtures.LazyChatCatalogTests.archive

    def test_batch_removes_selected_dormant_chats_attachments_and_memory_across_seal(self):
        store,sessions=self.archive()
        p=SelectionDeleteTests().panel();p.store=store;p.memory=PersistentMemory(self.root)
        p.session=sessions[2];p.session_order=[s['id'] for s in sessions]
        p._check_login=lambda:store.profile.check()
        p.delete_chat();perform=p._confirm.call_args.args[2]
        self.assertEqual(list(store.sessions.glob('*.json')),[]) # Preview is catalog-only.
        perform()
        self.assertEqual([row['id'] for row in store.list_sessions()],[sessions[2]['id']])
        self.assertEqual(p.memory.stats()['capsules'],1)
        self.runtime.close(self.session,writers_stopped=True)
        self.session=self.backend.login(fixtures.fixtures.OWNER);self.runtime.prepare(self.session)
        fresh=ChatStore(self.root)
        self.assertEqual([row['id'] for row in fresh.list_sessions()],[sessions[2]['id']])
        for session in sessions[:2]:
            self.assertIsNone(fresh.load_session(session['id']))
            self.assertFalse((fresh.attachments/session['id']).exists())
        self.assertEqual(PersistentMemory(self.root).stats()['capsules'],1)
        self.assertEqual(fresh.load_session(sessions[2]['id'])['messages'],sessions[2]['messages'])

if __name__=='__main__':unittest.main()
