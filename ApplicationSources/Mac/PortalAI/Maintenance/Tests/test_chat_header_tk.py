"""Measure the actual native-chat header in off-screen synthetic Tk windows."""
import ast
import gc
from pathlib import Path
import sys
import tkinter as tk
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'ControlCenter'), str(ROOT/'Agent'), str(ROOT/'Maintenance/Tests')]
import native_chat as chat
from tk_fixture_cleanup import finish_tk_fixture

MEASUREMENTS = []


def build_real_header(panel):
    tree = ast.parse((ROOT/'ControlCenter/native_chat.py').read_text(encoding='utf-8'))
    cls = next(row for row in tree.body if isinstance(row, ast.ClassDef) and row.name == 'NativeChat')
    function = next(row for row in cls.body if isinstance(row, ast.FunctionDef) and row.name == '_build_ui')
    header = []
    for row in function.body:
        # History now belongs to the actions row; include that row in the header fixture.
        if isinstance(row, ast.Assign) and any(isinstance(target, ast.Attribute) and target.attr == 'body_pane' for target in row.targets):
            break
        header.append(row)
    function.body = header
    function.name = 'header_fixture'
    namespace = dict(chat.__dict__)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                 '<actual-chat-header-fixture>', 'exec'), namespace)
    namespace['header_fixture'](panel)


class ChatHeaderTkTests(unittest.TestCase):
    def setUp(self):
        try: self.app = tk.Tk()
        except tk.TclError as exc: raise unittest.SkipTest('Tk unavailable: '+str(exc))
        self.addCleanup(self._cleanup_app)
        self.app.geometry('1260x250-10000-10000')
        self.errors = []
        self.app.report_callback_exception = lambda *args: self.errors.append(args)
        chat.apply_root_typography(self.app)
        self.panel = chat.NativeChat.__new__(chat.NativeChat)
        self.panel.host = self.app
        self.panel.toggle_history = lambda: None
        self.panel.COL = {'bg':'#11151A','card':'#171D23','panel':'#181E24','panel2':'#202831','text':'#F2F0EA',
                          'cyan':'#58B7C7','muted':'#9DA7AF'}
        build_real_header(self.panel)
        self.panel.model_name_lbl.configure(text='Qwen · Qwen3.8-27B-Abliterated-Q4_K_M.gguf')
        self.panel.model_lbl.configure(text='ready')

    def tearDown(self):
        self.assertEqual(self.errors, [])
        self.errors.clear()
        self._cleanup_app()
        self.panel = None
        gc.collect()

    def _cleanup_app(self):
        if self.app is not None:
            finish_tk_fixture(self.app)
            self.app = None

    def test_full_token_text_fits_default_narrow_and_compact_widths(self):
        for text in ('Last input est. ~8,354 · context 32,768 · reply cap 2,048',
                     'Last input est. ~8,354 · context 32,768 · request budget 28,000 · reply cap 2,048 · summary + 4 recent turns'):
            for width in (1260, 900, 640, 500):
                with self.subTest(width=width, characters=len(text)):
                    self.app.geometry(f'{width}x250-10000-10000')
                    self.panel.token_lbl.configure(text=text)
                    self.app.update_idletasks()
                    self.app.update()
                    label = self.panel.token_lbl
                    header = label.master
                    row = {'window_width':width,'characters':len(text),
                           'header_width':header.winfo_width(),'header_height':header.winfo_height(),
                           'token_width':label.winfo_width(),'token_requested_width':label.winfo_reqwidth(),
                           'token_height':label.winfo_height(),'token_requested_height':label.winfo_reqheight(),
                           'token_mapped':bool(label.winfo_ismapped()),'wrap_pixels':int(label.cget('wraplength'))}
                    MEASUREMENTS.append(row)
                    self.assertTrue(row['token_mapped'])
                    self.assertGreaterEqual(row['token_width'],row['token_requested_width'])
                    self.assertGreaterEqual(row['token_height'],row['token_requested_height'])
                    self.assertLessEqual(label.winfo_x()+row['token_width'],row['header_width'])
                    self.assertLessEqual(row['wrap_pixels'],330)
                    self.assertTrue(self.panel.history_btn.winfo_ismapped())
                    self.assertGreater(self.panel.model_name_lbl.master.winfo_width(),0)
                    self.assertLessEqual(row['header_height'],80)

    def test_late_resize_after_destroy_is_harmless(self):
        self.panel.token_lbl.destroy()
        self.panel._resize_token_label(SimpleNamespace(width=640))


if __name__ == '__main__': unittest.main()
