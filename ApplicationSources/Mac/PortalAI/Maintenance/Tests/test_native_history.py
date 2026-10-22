import sys, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ControlCenter'))
from native_history import render

class HistoryTests(unittest.TestCase):
    def fixture(self, count=25):
        rows=[{'id':str(i),'title':f'Saved chat {i}'} for i in range(count)]
        chat=SimpleNamespace(history_search=Mock(),_filtered_sessions=lambda:rows,store=SimpleNamespace(list_sessions=lambda:rows),
            busy=False,pending_attachments=[],session={'id':'0'},load_session=Mock(),_check_login=Mock())
        chat.history_search.get.return_value=''
        c=SimpleNamespace(chat=chat,tabs={},overrides={},views={'v':{'offset':0}})
        nodes=[];actions={};fields={};structure=[]
        def node(kind,label,**kw):nodes.append({'kind':kind,'label':label,**kw})
        def button(label,fn,key=None,available=True):
            nodes.append({'kind':'button','label':label,'key':key,'enabled':available})
            if available:actions[label]=fn
        render(c,node,button,fields,structure,'v')
        return c,nodes,actions,fields,rows
    def test_full_catalog_is_paged_and_open_has_one_explicit_target(self):
        c,n,a,f,rows=self.fixture();self.assertEqual(len([x for x in n if (x.get('key') or '').startswith('history_open_')]),20)
        a['Open · Saved chat 3']();c.chat.load_session.assert_called_once_with('3')
        a['Next chats']();self.assertEqual(c.tabs[('v','history_offset')],20)
    def test_stale_entry_and_pending_attachment_refuse_without_loading(self):
        for change in ('deleted','attachment','busy','closing'):
            c,n,a,f,rows=self.fixture()
            if change=='deleted':rows.clear()
            elif change=='attachment':c.chat.pending_attachments=['fixture']
            elif change=='closing':c.chat._closing=True
            else:c.chat.busy=True
            with self.assertRaises((RuntimeError,PermissionError)):a['Open · Saved chat 3']()
            c.chat.load_session.assert_not_called()
    def test_search_is_committed_explicitly_with_conflict_and_length_checks(self):
        c,n,a,f,rows=self.fixture();write=f['history_query']['prepare']('older message')
        c.chat.history_search.set.assert_not_called();write();c.chat.history_search.set.assert_called_once_with('older message')
        with self.assertRaises(ValueError):f['history_query']['prepare']('x'*501)
        c.chat.history_search.get.return_value='desktop changed'
        with self.assertRaises(RuntimeError):f['history_query']['prepare']('browser draft')
