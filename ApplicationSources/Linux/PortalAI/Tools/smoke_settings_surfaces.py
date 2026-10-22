"""Capture only synthetic settings windows; no accounts, models or hardware probes."""
import argparse
import json
from pathlib import Path
import sys
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'Tools'), str(ROOT/'Maintenance/Tests'), str(ROOT/'ControlCenter'), str(ROOT/'Agent')]
from test_settings_surfaces_tk import LIGHT, DARK, hardware_fixture, chat_fixture
from tk_fixture_cleanup import finish_tk_fixture
from smoke_account_panels import capture_window
from validation_artifacts import ValidationArtifacts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts-dir', required=True)
    args = parser.parse_args()
    artifacts = ValidationArtifacts(ROOT, args.artifacts_dir)
    app = tk.Tk(); app.title('PortalAI · synthetic settings fixture')
    errors = []; images = []; page = panel = None
    app.report_callback_exception = lambda *error: errors.append(str(error))
    try:
        for name, palette, width in (('light', LIGHT, 1080), ('dark', DARK, 1080), ('narrow', DARK, 560)):
            app.geometry(f'{width}x650+30+30'); app.configure(bg=palette['bg'])
            page, skin = hardware_fixture(app, palette)
            app.update()
            images.append(capture_window(app, artifacts.path(f'hardware-settings-{name}.png')))
            page.tabs.select('media'); app.update()
            images.append(capture_window(app, artifacts.path(f'media-settings-{name}.png')))
            page.destroy(); page = None
            for child in app.winfo_children(): child.destroy()
            panel = chat_fixture(app, palette)
            app.update()
            images.append(capture_window(app, artifacts.path(f'chat-settings-{name}.png')))
            if name == 'dark':
                panel._sheet_skin.canvas.yview_moveto(1)
                images.append(capture_window(app, artifacts.path('chat-settings-dark-lower.png')))
            panel._close_sheet(); panel = None
            for child in app.winfo_children(): child.destroy()
        report = {'synthetic_only':True, 'production_accounts_opened':False,
                  'model_or_hardware_probes_started':False, 'callback_errors':errors, 'screenshots':images}
        artifacts.path('settings-surfaces-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if errors: raise RuntimeError(errors)
        print(json.dumps(report))
    finally:
        if page: page.destroy()
        if panel: panel._close_sheet()
        page = panel = None
        finish_tk_fixture(app)


if __name__ == '__main__': main()
