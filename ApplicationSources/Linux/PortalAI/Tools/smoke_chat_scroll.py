"""Time real Tk scrolling/tab remapping on synthetic cards; no private history."""
import argparse
import cProfile
import io
import json
from pathlib import Path
import pstats
import sys
import time
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/p) for p in ('ControlCenter', 'Agent', 'Tools', 'Maintenance/Tests')]
from chat_zoom import ChatZoom
from conversation_cards import ornate_frame
from tk_fixture_cleanup import finish_tk_fixture
from validation_artifacts import ValidationArtifacts


def run():
    app = tk.Tk(); app.geometry('900x700+3500+3500')
    chat = tk.Text(app); chat.pack(fill='both', expand=True)
    zoom = ChatZoom(chat, {}, lambda: None)
    colors = {'bg':'#efe8dc', 'card':'#f8f3ea', 'text':'#222222'}
    try:
        for i in range(60):
            frame = ornate_frame(chat, colors)
            for j in range(4):
                tk.Label(frame, text=f'Synthetic card {i} row {j} - '+('text '*15)).pack()
            chat.window_create('end', window=frame)
            chat.insert('end', '\n'+'Synthetic reply text. '*50+'\n')
        app.update(); profile = cProfile.Profile(); profile.enable(); start = time.perf_counter()
        for i in list(range(50))+list(range(49, -1, -1)):
            chat.yview_moveto(i/50); app.update()
        profile.disable(); elapsed = time.perf_counter()-start
        stream = io.StringIO()
        stats = pstats.Stats(profile, stream=stream).strip_dirs().sort_stats('cumulative')
        stats.print_stats(20)
        font_updates = sum(row[1] for key,row in stats.stats.items() if key[0]=='font.py' and key[2]=='config')
        start = time.perf_counter()
        for _ in range(10):
            chat.pack_forget(); app.update()
            chat.pack(fill='both', expand=True); app.update()
        return {'scrolls':100, 'cards':60, 'scroll_seconds':elapsed,
                'scroll_font_updates':font_updates, 'ten_remaps_seconds':time.perf_counter()-start,
                'evidence':'Synthetic Tk only; not model inference latency'}, stream.getvalue()
    finally:
        zoom.close(); finish_tk_fixture(app)


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir', required=True)
    args = parser.parse_args(); artifacts = ValidationArtifacts(ROOT, args.artifacts_dir)
    report, profile = run()
    artifacts.path('profile.txt').write_text(profile, encoding='utf-8')
    artifacts.path('report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
