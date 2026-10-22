"""Real Tk/FFmpeg assistant-image rendering with disposable output files."""
import base64
import os
from pathlib import Path
import queue
import struct
import sys
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/p) for p in ('ControlCenter', 'Agent', 'Maintenance/Tests')]
from native_chat import NativeChat
import inline_chat_images as images
from profile_paths import ProfileLocked
from tk_fixture_cleanup import finish_tk_fixture


def png(path):
    def chunk(tag, data):
        return struct.pack('>I', len(data))+tag+data+struct.pack('>I', zlib.crc32(tag+data)&0xffffffff)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR', struct.pack('>IIBBBBB', 64, 32, 8, 2, 0, 0, 0))+
        chunk(b'IDAT', zlib.compress((b'\0'+b'\x20\xa0\xe0'*64)*32))+chunk(b'IEND', b''))


class ImageLinks(unittest.TestCase):
    def test_url_mapping_is_bounded_and_does_not_fetch(self):
        self.assertEqual(images.local_reference('http://127.0.0.1:8765/Images/a%20b.png?portal_token=old'), 'Outputs/Images/a b.png')
        self.assertEqual(images.local_reference('http://localhost:8765/Images/a.png'), 'Outputs/Images/a.png')
        for url in ('https://example.com/a.png', 'http://127.0.0.1:8080/a.png',
                    'http://user@127.0.0.1:8765/a.png', 'http://127.0.0.1:8765/%2e%2e/a.png',
                    'http://127.0.0.1:8765/a%5cb.png', 'http://127.0.0.1:8765/a.txt'):
            self.assertIsNone(images.local_reference(url))

    def test_complete_images_only_and_code_is_preserved(self):
        raw = '![Generated image](http://127.0.0.1:8765/Images/a.png)'
        self.assertEqual(len(list(images.image_links('Here is the image: '+raw))), 1)
        self.assertEqual(list(images.image_links(raw[:-1])), [])
        self.assertEqual(list(images.image_links('`'+raw+'`')), [])
        self.assertEqual(list(images.image_links('```markdown\n'+raw+'\n```')), [])


class InlineImagesTk(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = Path(self.temp.name)
        self.source = self.fixture/'Outputs/Images/test image.png'; png(self.source)
        self.app = tk.Tk(); self.app.geometry('620x540+30+30')
        self.p = NativeChat.__new__(NativeChat)
        self.p.app = self.app; self.p.root = ROOT; self.p.host = self.app
        self.p.chat = tk.Text(self.app); self.p.chat.pack(fill='both', expand=True)
        self.p.COL = {'bg':'#f8f3ea', 'card':'#f8f3ea', 'text':'#222222', 'muted':'#555555'}
        self.p.ev = queue.Queue(); self.p._closing = False
        self.p._check_login = lambda: None
        self.p._resolve_private_reference = lambda value, **kw: (self.fixture/value).resolve()
        self.threads = []
        def thread(**kw):
            t = threading.Thread(**kw); self.threads.append(t); return t
        self.p._thread = thread

    def tearDown(self):
        self.p._closing = True
        for thread in self.threads: thread.join(4)
        finish_tk_fixture(self.app)

    def finish(self):
        kind, event = self.p.ev.get(timeout=10)
        self.assertEqual(kind, 'inline_image_ready')
        images.finish(self.p, event); self.app.update()
        return event

    def test_streamed_markdown_renders_once_without_changing_surrounding_text(self):
        self.p.assistant_text('Here is ', stream=True)
        self.p.assistant_text('![Generated image](http://127.0.0.1:8765/Images/test%20', stream=True)
        self.assertEqual(self.p.chat.window_names(), ())
        self.p.assistant_text('image.png)', stream=True)
        self.p.assistant_text('\nDone.', stream=True)
        event = self.finish()
        self.assertIsNone(event[3]); self.assertEqual(len(self.p.chat.window_names()), 1)
        self.assertEqual(self.p.chat.get('1.0', 'end-1c'), 'Here is \nDone.')
        frame = event[0]
        label = next(w for container in frame._portalai_preview_body.winfo_children() for w in container.winfo_children()
                     if hasattr(w, '_portalai_image'))
        self.assertEqual(label._portalai_image.width(), 520)

    def test_plain_stream_does_not_scan_transcript_for_images(self):
        with patch.object(images, 'render_links', side_effect=AssertionError('Scanned plain text')):
            for _ in range(100):self.p.assistant_text('Ordinary response (some detail). ', stream=True)
        self.assertEqual(len(self.threads), 0)

    def test_minimized_loading_preview_stays_minimized_and_restores_without_decode(self):
        self.p.assistant_text('![Image](http://127.0.0.1:8765/Images/test%20image.png)')
        frame = self.app.nametowidget(self.p.chat.window_names()[0])
        frame._portalai_preview_toggle.invoke(); self.app.update()
        self.finish()
        self.assertFalse(frame._portalai_preview_expanded)
        self.assertEqual(frame._portalai_preview_body.winfo_manager(), '')
        for _ in range(2):
            frame._portalai_preview_toggle.invoke(); self.app.update()
            self.assertEqual(frame._portalai_preview_body.winfo_manager(), 'pack')
            frame._portalai_preview_toggle.invoke(); self.app.update()
        self.assertEqual(len(self.threads), 1)

    def test_split_markdown_opening_is_rendered(self):
        self.p.assistant_text('Here: !', stream=True)
        self.p.assistant_text('[Image](http://127.0.0.1:8765/Images/test%20image.png)', stream=True)
        self.assertIsNone(self.finish()[3])

    def test_saved_reply_and_expired_preview_token_use_current_local_output(self):
        self.p.assistant_text('![Image](http://127.0.0.1:8765/Images/test%20image.png?portal_token=expired)\n')
        self.assertIsNone(self.finish()[3])

    def test_same_markdown_inside_code_is_not_replaced(self):
        raw='![Image](http://127.0.0.1:8765/Images/test%20image.png)'
        self.p.assistant_text('`'+raw+'`\n'+raw+'\n'+raw)
        self.finish();self.finish()
        self.assertEqual(self.p.chat.get('1.0','end-1c'),'`'+raw+'`\n\n')
        self.assertEqual(len(self.p.chat.window_names()),2)

    def test_another_profile_or_nonoutput_path_never_decodes(self):
        outside = self.fixture/'Private/other.png'; png(outside)
        with patch.object(images.subprocess, 'Popen') as start:
            with self.assertRaises(ValueError): images.thumbnail_bytes(self.p, str(outside))
        start.assert_not_called()

    def test_revocation_before_publication_leaves_no_image(self):
        self.p.assistant_text('![Image](http://127.0.0.1:8765/Images/test%20image.png)')
        _, event = self.p.ev.get(timeout=10)
        def revoked(): raise ProfileLocked('Ended login')
        self.p._check_login = revoked
        with self.assertRaises(ProfileLocked): images.finish(self.p, event)
        self.assertTrue(event[1].winfo_exists())
        self.assertEqual(str(event[1].cget('image')), '')

    def test_history_switch_discards_late_preview(self):
        self.p.assistant_text('![Image](http://127.0.0.1:8765/Images/test%20image.png)')
        _, event = self.p.ev.get(timeout=10)
        event[0].destroy()
        images.finish(self.p, event)


if __name__ == '__main__': unittest.main()
