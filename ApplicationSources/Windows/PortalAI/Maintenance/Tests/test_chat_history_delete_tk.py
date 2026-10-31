"""Real Tk confirmation content, scrolling and Cancel; synthetic titles only."""
import os,sys,tkinter as tk,unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('ControlCenter','Agent','Tools','Maintenance/Tests')]
from native_chat import NativeChat
from tk_fixture_cleanup import finish_tk_fixture
from test_account_presentation_tk import LIGHT,DARK


def descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from descendants(child)


class DeletePreviewTkTests(unittest.TestCase):
    def setUp(self):
        self.app=tk.Tk();self.app.title('PortalAI synthetic history-delete test');self.app.withdraw()
        self.addCleanup(finish_tk_fixture,self.app)
        self.errors=[];self.app.report_callback_exception=lambda *args:self.errors.append(str(args))
        self.p=NativeChat.__new__(NativeChat);self.p.host=self.p.app=self.app
        self.p._sheet_overlay=None;self.p._stop_embedded_media=Mock()

    def test_all_titles_scroll_and_buttons_fit_in_both_themes(self):
        p=self.p
        for theme,palette in (('light',LIGHT),('dark',DARK)):
            p.COL={**palette,'gold':palette.get('gold_mid','#A88446'),'cyan':palette.get('accent','#58B7C7'),'bad':'#E47772'}
            for width in (720,1260):
                self.app.geometry(f'{width}x820+40+40')
                # Map only this disposable window; no account, microphone or model.
                self.app.deiconify();self.app.update()
                yes=Mock();items=tuple(f'{n}. Synthetic selected chat {n}' for n in range(1,81))
                p._confirm('Delete 80 chats','Delete 80 selected chats?\n\nThis removes their raw history, chat-owned attachments, and learned memory observations.',yes,yes_text='Delete 80 chats',danger=True,items=items)
                self.app.update()
                widgets=list(descendants(p._sheet_overlay))
                boxes=[w for w in widgets if isinstance(w,tk.Text)]
                self.assertEqual(len(boxes),1);box=boxes[0]
                self.assertEqual(box.get('1.0','end-1c'),'\n'.join(items))
                self.assertEqual(str(box.cget('state')),'disabled')
                self.assertLess(box.yview()[1],1)
                box.yview_moveto(1);self.app.update();self.assertAlmostEqual(box.yview()[1],1)
                buttons={str(w.cget('text')):w for w in widgets if w.winfo_class() in ('Button','TButton')}
                for label in ('Cancel','Delete 80 chats'):
                    button=buttons[label];self.assertTrue(button.winfo_ismapped())
                    self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),self.app.winfo_rooty()+self.app.winfo_height())
                destination=os.environ.get('PORTALAI_HISTORY_SCREENSHOTS')
                if destination:
                    from smoke_account_panels import capture_window
                    box.yview_moveto(0);capture_window(self.app,Path(destination)/f'delete-{theme}-{width}.png')
                buttons['Cancel'].invoke();self.app.update();yes.assert_not_called()
                self.assertIsNone(p._sheet_overlay)
        self.assertEqual(self.errors,[])

    def test_confirmation_invokes_action_once_and_closes(self):
        self.p.COL={**DARK,'gold':'#A88446','cyan':'#58B7C7','bad':'#E47772'}
        self.app.geometry('720x820');self.app.deiconify();self.app.update()
        yes=Mock();self.p._confirm('Delete 2 chats','Delete 2 selected chats?',yes,yes_text='Delete 2 chats',danger=True,items=('1. First','2. Second'))
        button=next(w for w in descendants(self.p._sheet_overlay) if w.winfo_class() in ('Button','TButton') and str(w.cget('text'))=='Delete 2 chats')
        button.invoke();yes.assert_called_once();self.assertIsNone(self.p._sheet_overlay)

if __name__=='__main__':unittest.main()
