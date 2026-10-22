"""Compact chat banner and storage display in a disposable launcher account."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/p) for p in ('Tools', 'ControlCenter', 'Agent')]
from validation_artifacts import ValidationArtifacts
from smoke_login_continuity import run
from smoke_account_panels import capture_window


def inspect(built, app, destination):
    def settle():
        until = time.monotonic()+.3
        while time.monotonic() < until: app.update(); time.sleep(.01)
    panel = built['native_chat_panel']; controller = built['portal_compact_mode']
    rows = []
    for mode in ('light', 'dark'):
        if mode == 'dark': built['toggle_theme']()
        controller.enter(); settle()
        if not controller.expanded: controller.toggle_chat()
        for width in (900, 1500):
            app.geometry(f'{width}x760+40+40'); settle()
            header = panel.model_name_lbl.master.master
            banner = header.master
            gap = banner.winfo_height() - header.winfo_y() - header.winfo_height()
            assert gap >= 9, gap
            assert banner._portalai_conversation_border.canvas.find_withtag('ornate')
            rows.append({'theme': mode, 'width': width, 'bottom_clearance': gap})
            capture_window(app, destination/f'compact-{mode}-{width}.png')
        controller.exit(); settle()
    built['toggle_theme'](); settle()  # Return to the harness's original light theme.
    page = built['storage_page']
    from runtime_policy import storage_budget
    page.variables['output_reserve_gib'].set('123')
    page.refresh_budget(storage_budget(built['root']))
    assert page.variables['output_reserve_gib'].get() == '123'
    (destination/'layout.json').write_text(json.dumps(rows, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts-dir', required=True)
    args = parser.parse_args(); artifacts = ValidationArtifacts(ROOT, args.artifacts_dir)
    try: report = run(artifacts.path(), inspector=inspect)
    except Exception as exc: report = {'passed': False, 'error': str(exc)}
    artifacts.path('report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report)); raise SystemExit(not report.get('passed'))
