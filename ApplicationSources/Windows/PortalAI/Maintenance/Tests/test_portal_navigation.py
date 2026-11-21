import queue
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ControlCenter'))
from portal_navigation import Navigation


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.navigate=Mock();self.utilities=Mock();self.locked=False
        self.nav=Navigation(Path(__file__).parent,queue.Queue(),lambda:{'page':'chat','pages':['chat','controls']},self.navigate,self.utilities,lambda:self.locked)

    def test_navigation_uses_observed_page_and_consumes_token(self):
        state=self.nav.execute({'action':'state'},lambda:None)
        args={'action':'navigate','page':'controls','observation':state['observation']}
        self.nav.execute(args,lambda:None);self.navigate.assert_called_once_with('controls')
        with self.assertRaises(ValueError):self.nav.execute(args,lambda:None)

    def test_locked_and_stopped_requests_cannot_dispatch(self):
        self.locked=True
        with self.assertRaises(PermissionError):self.nav.execute({'action':'state'},lambda:None)
        cancel=threading.Event();cancel.set();reply=queue.Queue()
        self.nav.dispatch(({'action':'click','button':'Utilities'},lambda:None,cancel,reply))
        self.utilities.assert_not_called();self.assertTrue(reply.empty())

    def test_no_arbitrary_button_or_page_is_exposed(self):
        for args in ({'action':'navigate','page':'__dict__'},{'action':'click','button':'Wipe all accounts'}):
            args['observation']=self.nav.snapshot()['observation']
            with self.assertRaises(ValueError):self.nav.execute(args,lambda:None)
        self.navigate.assert_not_called();self.utilities.assert_not_called()

    def test_projection_invokes_existing_visible_button(self):
        button=Mock();button.cget.return_value='PortalAI Home Assistant Projection'
        dialog=Mock(closed=False,buttons=[(button,None)]);dialog.status.get.return_value='Opened separately.'
        self.utilities.return_value=dialog
        state=self.nav.execute({'action':'click','button':'Utilities','observation':self.nav.snapshot()['observation']},lambda:None)
        result=self.nav.execute({'action':'click','button':'PortalAI Home Assistant Projection','observation':state['observation']},lambda:None)
        button.invoke.assert_called_once();self.assertEqual(result['utility_status'],'Opened separately.')


if __name__=='__main__':unittest.main()
