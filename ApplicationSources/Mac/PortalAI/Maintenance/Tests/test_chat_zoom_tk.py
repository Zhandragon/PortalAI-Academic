"""Synthetic Tk transcript only: no profiles, model servers or user history."""
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import tkinter as tk
from tkinter import font as tkfont
from tkinter.scrolledtext import ScrolledText

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'ControlCenter'), str(ROOT / 'Agent')]
from chat_zoom import ChatZoom, normalize_zoom, image_size, resize_ppm
from conversation_cards import ornate_frame, preview_label, refresh_borders
from trace_resize import install_trace_resizer
from tk_fixture_cleanup import finish_tk_fixture

COLORS = {'bg': '#efe8dc', 'card': '#f8f3ea', 'panel2': '#e9e0d2', 'muted': '#6e665e',
          'gold': '#a87d32', 'tool': '#d9be78', 'text': '#202224'}


class ZoomPolicyTests(unittest.TestCase):
    def test_invalid_and_bounded_preference(self):
        self.assertEqual([normalize_zoom(v) for v in (None, 'bad', float('nan'), float('inf'))], [100]*4)
        self.assertEqual(normalize_zoom(-1), 75)
        self.assertEqual(normalize_zoom(999999), 200)

    def test_media_aspect_and_memory_limit(self):
        self.assertEqual(image_size(200, 100, 150, 900), (300, 150))
        self.assertEqual(image_size(200, 100, 200, 300), (300, 150))
        self.assertLessEqual(max(image_size(4000, 4000, 200, 8000)), 1400)

    def test_ppm_pixels_scale_exactly_and_refuse_unbounded(self):
        data = b'P6\n2 1\n255\n\xff\x00\x00\x00\xff\x00'
        self.assertEqual(resize_ppm(data, 4, 1), b'P6\n4 1\n255\n'+b'\xff\x00\x00'*2+b'\x00\xff\x00'*2)
        with self.assertRaises(ValueError): resize_ppm(data, 9000, 9000)


class ChatZoomTkTests(unittest.TestCase):
    def setUp(self):
        self.app = tk.Tk()
        self.callback_errors = []
        self.app.report_callback_exception = lambda kind, value, trace: self.callback_errors.append(str(value))
        self.app.geometry('900x700+3500+3500')
        self.chat = ScrolledText(self.app, width=70, height=22, font=('Segoe UI', 10), bg=COLORS['bg'])
        self.chat.pack(fill='both', expand=True)
        self.chat.tag_configure('speaker', font=('Segoe UI', 10, 'bold'))
        self.composer = tk.Text(self.app, height=2, font=('Segoe UI', 10))
        self.composer.pack(fill='x')
        self.settings, self.save = {}, Mock()
        self.zoom = ChatZoom(self.chat, self.settings, self.save)
        self.pump(.12)

    def tearDown(self):
        self.zoom.close()
        finish_tk_fixture(self.app)
        self.assertFalse(self.callback_errors, self.callback_errors)

    def pump(self, seconds=.12):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.update()
            time.sleep(.01)

    def size(self, widget):
        return int(tkfont.Font(root=self.app, font=widget.cget('font')).cget('size'))

    def test_control_wheel_scales_tags_not_composer_and_normal_scroll_remains(self):
        self.chat.insert('end', 'Line\n' * 100)
        self.chat.yview_moveto(0)
        ordinary = self.chat.bind('<MouseWheel>')
        self.chat.event_generate('<Control-MouseWheel>', delta=120)
        self.pump()
        self.assertEqual(self.zoom.percent, 110)
        self.assertEqual(self.size(self.chat), 11)
        self.assertEqual(self.size(self.composer), 10)
        tag = tkfont.Font(root=self.app, font=self.chat.tag_cget('speaker', 'font'))
        self.assertEqual(int(tag.cget('size')), 11)
        self.assertEqual(self.chat.bind('<MouseWheel>'), ordinary)
        self.chat.event_generate('<MouseWheel>', delta=-120)
        self.pump()
        self.assertGreater(self.chat.yview()[0], 0)

    def test_new_trace_children_inherit_zoom_without_replaying_content(self):
        self.zoom.set_percent(150)
        card = ornate_frame(self.chat, COLORS)
        label = tk.Label(card, text='Thinking', font=('Segoe UI', 10))
        label.pack()
        text = tk.Text(card, height=4, font=('Consolas', 10))
        text.insert('end', 'Original reasoning stays in place.')
        text.pack()
        self.chat.window_create('end', window=card)
        self.pump()
        self.assertEqual(self.size(label), 15)
        self.assertEqual(self.size(text), 15)
        self.assertEqual(text.get('1.0', 'end-1c'), 'Original reasoning stays in place.')
        self.zoom.set_percent(100)
        self.assertEqual(self.size(text), 10)

    def test_scrolling_and_returning_to_chat_do_not_reset_transcript_fonts(self):
        for i in range(25):
            card = ornate_frame(self.chat, COLORS)
            for _ in range(3):
                tk.Label(card, text=f'Card {i}', font=('Segoe UI', 10)).pack()
            self.chat.window_create('end', window=card)
            self.chat.insert('end', '\n' + 'Reply text. '*25 + '\n')
        for pos in range(20):
            self.chat.yview_moveto(pos/20); self.app.update()
        self.pump()
        with patch.object(tkfont.Font, 'configure', side_effect=AssertionError('Scroll reset a font')):
            for pos in list(range(20)) + list(range(19, -1, -1)):
                self.chat.yview_moveto(pos/20); self.app.update()
            self.chat.frame.pack_forget(); self.app.update()
            self.chat.frame.pack(fill='both', expand=True); self.pump()
        self.assertFalse(self.callback_errors)

    def test_matching_card_fonts_share_one_zoom_font(self):
        labels=[]
        for _ in range(15):
            label=tk.Label(self.chat,text='Same font',font=('Segoe UI',10))
            self.chat.window_create('end',window=label);self.chat.insert('end','\n')
            labels.append(label)
        self.pump()
        self.assertEqual(len({str(label.cget('font')) for label in labels}),1)
        self.zoom.set_percent(150);self.pump()
        self.assertEqual({self.size(label) for label in labels},{15})

    def test_first_map_at_normal_zoom_keeps_original_font_specification(self):
        label=tk.Label(self.chat,text='Cold scroll card',font=('Segoe UI',10))
        original=label.cget('font')
        self.chat.window_create('end',window=label);self.pump()
        self.assertEqual(label.cget('font'),original)
        self.zoom.set_percent(150);self.pump()
        self.assertEqual(self.size(label),15)
        self.zoom.set_percent(100);self.pump()
        self.assertEqual(self.size(label),10)

    def test_preview_grows_preserves_aspect_and_returns_original(self):
        card = ornate_frame(self.chat, COLORS)
        image = tk.PhotoImage(master=self.app, width=200, height=100)
        image.put('#a87d32', to=(0, 0, 200, 100))
        label = preview_label(card, image, COLORS)
        self.chat.window_create('end', window=card)
        self.pump()
        self.zoom.set_percent(150)
        self.pump(.3)
        displayed = label.cget('image')
        self.assertEqual(int(label.tk.call('image', 'width', displayed)), 300)
        self.assertEqual(int(label.tk.call('image', 'height', displayed)), 150)
        self.zoom.set_percent(100)
        self.pump(.2)
        self.assertEqual(str(label.cget('image')), str(image))

    def test_transparent_preview_composites_on_current_theme_without_black_box(self):
        image = tk.PhotoImage(master=self.app, width=2, height=1)
        image.put('red', to=(0, 0, 1, 1))
        label = tk.Label(self.chat, image=image, bg=COLORS['card'])
        self.chat.window_create('end', window=label)
        self.pump()
        self.zoom.set_percent(200)
        self.pump()
        photo = self.zoom._images[str(label)]['display']
        self.assertEqual(photo.get(3, 0), (248, 243, 234))
        label.configure(bg='#181b1e')
        self.zoom._schedule_images()
        self.pump()
        self.assertEqual(self.zoom._images[str(label)]['display'].get(3, 0), (24, 27, 30))

    def test_deleted_history_releases_widgets_fonts_images_and_bindings(self):
        baseline = len(self.zoom._widgets), len(self.zoom._bindings), len(self.zoom._fonts)
        for _ in range(15):
            frame = tk.Frame(self.chat)
            tk.Label(frame, text='temporary history').pack()
            self.chat.window_create('end', window=frame)
            self.pump(.02)
            self.chat.delete('1.0', 'end')
            self.pump(.02)
        self.assertEqual((len(self.zoom._widgets), len(self.zoom._bindings), len(self.zoom._fonts)), baseline)

    def test_long_media_filename_and_actions_stay_in_narrow_conversation_at_max_zoom(self):
        from native_chat import NativeChat
        panel = NativeChat.__new__(NativeChat)
        panel.chat, panel.app, panel.host = self.chat, self.app, self.app
        panel.COL = {**COLORS, 'cyan': '#3e91a2'}
        panel._resolve_private_reference = lambda value: Path(value)
        self.app.geometry('480x700+3500+3500')
        panel.render_media_card({'path': 'synthetic_image_name_that_should_not_force_the_controls_outside_the_chat_window.png'})
        self.pump(.25)
        frame = self.app.nametowidget(self.chat.window_names()[-1])
        self.assertLessEqual(frame.winfo_reqwidth(), self.chat.winfo_width())
        self.zoom.set_percent(200)
        self.pump(.3)
        self.assertLessEqual(frame.winfo_reqwidth(), self.chat.winfo_width())

    def test_profile_save_debounced_and_no_late_save_on_close(self):
        self.zoom.set_percent(120)
        self.zoom.set_percent(140)
        self.pump(.5)
        self.save.assert_called_once_with()
        self.assertEqual(self.settings['chat_zoom_percent'], 140)
        self.zoom.set_percent(160)
        self.zoom.close()
        self.pump(.5)
        self.save.assert_called_once_with()

    def test_locked_overlay_rejects_zoom_and_composer_binding_absent(self):
        self.app._portalai_modal_guard = SimpleNamespace(surface=object())
        self.zoom._wheel(SimpleNamespace(delta=120))
        self.assertEqual(self.zoom.percent, 100)
        self.assertEqual(self.composer.bind('<Control-MouseWheel>'), '')
        self.app._portalai_modal_guard = SimpleNamespace(surface=None)

    def test_keyboard_reset_context_menu_and_saved_preference(self):
        self.zoom._key(None, 1)
        self.zoom._key(None, 0)
        self.assertEqual(self.zoom.percent, 100)
        self.zoom.set_percent(140)
        menu = tk.Menu(self.app, tearoff=False)
        self.zoom.add_menu(menu)
        menu.invoke(2)
        self.assertEqual(self.zoom.percent, 100)
        self.zoom.close()
        self.settings['chat_zoom_percent'] = 160
        # An independent transcript simulates a new launcher using saved profile settings.
        second = tk.Text(self.app, font=('Segoe UI', 10))
        self.zoom = ChatZoom(second, self.settings, self.save)
        self.assertEqual(self.size(second), 16)

    def test_resize_trace_pushes_following_text_and_survives_collapse(self):
        card = ornate_frame(self.chat, COLORS)
        body = tk.Frame(card)
        body.pack()
        text = tk.Text(body, height=3, width=45, font=('Consolas', 9))
        text.pack()
        grip = install_trace_resizer(body, text, self.chat, COLORS)
        self.chat.window_create('end', window=card)
        self.chat.insert('end', '\nFollowing reply')
        self.pump()
        before = self.chat.dlineinfo('2.0')[1]
        grip._portalai_resize_rows(9)
        self.pump()
        after = self.chat.dlineinfo('2.0')[1]
        self.assertGreater(after, before + 40)
        body.pack_forget()
        self.pump()
        body.pack()
        self.pump()
        self.assertEqual(int(text.cget('height')), 9)
        grip._portalai_resize_rows(1000)
        self.assertEqual(int(text.cget('height')), 50)
        grip._portalai_resize_rows(-1)
        self.assertEqual(int(text.cget('height')), 3)

    def test_ornate_border_theme_refresh_tracks_actual_dark_parent(self):
        card = ornate_frame(self.chat, COLORS)
        tk.Label(card, text='Media preview', bg=COLORS['card']).pack(padx=20, pady=20)
        self.chat.window_create('end', window=card)
        self.pump()
        dark = {**COLORS, 'bg': '#101214', 'card': '#181b1e'}
        self.chat.configure(bg=dark['bg'])
        card.configure(bg=dark['card'])
        refresh_borders(self.chat, dark)
        self.pump()
        canvas = card._portalai_conversation_border.canvas
        self.assertEqual(canvas.itemcget(canvas.find_withtag('ornate-corner-mask')[0], 'fill'), dark['bg'])

    def test_native_trace_hook_retains_expansion_resize_and_existing_contents(self):
        from native_chat import NativeChat
        panel = NativeChat.__new__(NativeChat)
        panel.chat, panel.app, panel.host = self.chat, self.app, self.app
        panel.COL = {**COLORS, 'thinking': COLORS['muted'], 'panel': COLORS['card']}
        panel.settings = {'collapse_thinking_blocks': False}
        panel._trace_blocks = []
        panel._trace_flush_after = None
        block = panel.create_trace_block('thinking', 'Thinking', initial='Saved synthetic reasoning')
        self.pump()
        self.assertTrue(hasattr(block['frame'], '_portalai_conversation_border'))
        block['resizer']._portalai_resize_rows(15)
        panel._set_trace_block_expanded(block, False)
        panel._set_trace_block_expanded(block, True)
        self.assertEqual(int(block['text'].cget('height')), 15)
        self.assertIn('Saved synthetic reasoning', block['text'].get('1.0', 'end'))


if __name__ == '__main__':
    unittest.main()
