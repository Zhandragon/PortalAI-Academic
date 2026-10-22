"""Render isolated synthetic conversation cards; never open live user profiles."""
import argparse
import json
from pathlib import Path
import sys
import time
import tkinter as tk
from tkinter.scrolledtext import ScrolledText

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'ControlCenter'), str(ROOT / 'Agent'), str(ROOT / 'Maintenance/Tests')]
from native_chat import NativeChat
from chat_zoom import ChatZoom
from elegant_native_ui import ElegantButton
from validation_artifacts import ValidationArtifacts
from smoke_account_panels import capture_window
from tk_fixture_cleanup import finish_tk_fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    args = parser.parse_args()
    artifacts = ValidationArtifacts(ROOT, args.artifacts_dir)
    results = []
    for theme, width, zoom in [('light', 1050, 100), ('dark', 1050, 150), ('narrow', 620, 120)]:
        colors = {'bg': '#efe8dc', 'panel': '#e6dccb', 'panel2': '#e9e0d2', 'card': '#f8f3ea',
                  'text': '#202224', 'muted': '#6e665e', 'thinking': '#6e665e',
                  'gold': '#a87d32', 'tool': '#d9be78', 'cyan': '#3e91a2'}
        if theme == 'dark':
            colors.update(bg='#101214', panel='#181b1e', panel2='#23272b', card='#181b1e',
                          text='#eee7da', muted='#aaa39b', thinking='#aaa39b')
        app = tk.Tk()
        app.geometry(f'{width}x820+30+30')
        app.title('PortalAI synthetic chat layout — no account or inference')
        panel = NativeChat.__new__(NativeChat)
        try:
            panel.chat = ScrolledText(app, bg=colors['bg'], fg=colors['text'], relief='flat',
                                      wrap='word', font=('Segoe UI', 10), width=1)
            panel.chat.pack(fill='both', expand=True)
            panel.COL, panel.app, panel.host = colors, app, app
            panel._trace_blocks, panel._trace_flush_after = [], None
            panel.settings = {'collapse_thinking_blocks': False}
            panel.photo_refs = []
            panel._resolve_private_reference = lambda value: Path(value)
            panel.chat_zoom = ChatZoom(panel.chat, panel.settings, lambda: None)
            panel.chat.insert('end', 'Synthetic conversation preview\nCtrl + scroll zooms this conversation. Ctrl+0 resets.\n\n')
            block = panel.create_trace_block('thinking', 'Thinking', initial=(
                'The candidate is downloaded. Next I will edit the requested area and preserve the other details.\n'
                'This synthetic preview checks layout and readability only.\n' * 3))
            block['resizer']._portalai_resize_rows(5)
            panel.chat.insert('end', '\nText below the trace moves when its bottom handle is dragged.\n\n')
            panel.create_trace_block('tool', 'Tool · inspect image', collapsed=True, initial='Synthetic tool result retained.')
            photo = tk.PhotoImage(master=app, width=320, height=140)
            photo.put('#3e91a2', to=(0, 0, 320, 140))
            photo.put('#a87d32', to=(24, 22, 295, 120))
            photo.put('#e9e0d2', to=(36, 34, 284, 108))
            preview = artifacts.path('synthetic-preview.png')
            photo.write(str(preview), format='png')
            panel.render_media_card({'path': str(preview), 'thumb': str(preview)})
            last = app.nametowidget(panel.chat.window_names()[-1])
            stack = list(last.winfo_children())
            while stack:
                item = stack.pop(0)
                if isinstance(item, ElegantButton) and item.cget('text') == '▸':
                    item.invoke()
                    break
                stack.extend(item.winfo_children())
            panel.chat_zoom.set_percent(zoom)
            end = time.monotonic() + .5
            while time.monotonic() < end:
                app.update(); time.sleep(.01)
            panel.chat.yview_moveto(0)
            results.append(capture_window(app, artifacts.path(f'chat-zoom-{theme}.png')))
        finally:
            panel.chat_zoom.close()
            finish_tk_fixture(app)
    report = {'synthetic_only': True, 'production_profiles_opened': False, 'screenshots': results}
    artifacts.path('chat-zoom-visuals.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
