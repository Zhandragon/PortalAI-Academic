"""Screenshot the real chat layout with harmless synthetic rows and no services."""
import argparse
import json
from pathlib import Path
import sys
import time
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'ControlCenter'), str(ROOT / 'Agent'), str(ROOT / 'Maintenance/Tests')]
from test_chat_layout_tk import build_panel, LIGHT, DARK
from tk_fixture_cleanup import finish_tk_fixture
from validation_artifacts import ValidationArtifacts
from smoke_account_panels import capture_window


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifacts-dir', type=Path, required=True)
    args = parser.parse_args()
    artifacts = ValidationArtifacts(ROOT, args.artifacts_dir)
    report = {'synthetic_only': True, 'production_profiles_opened': False, 'screenshots': []}
    for name, colors, width, preferred, zoom in (
            ('light', LIGHT, 1250, 320, 100), ('dark', DARK, 1250, 320, 125),
            ('narrow', LIGHT, 680, 230, 100)):
        app = tk.Tk()
        app.geometry(f'{width}x860+30+30')
        app.title('PortalAI synthetic chat layout — no profile or model')
        panel = build_panel(app, colors=colors, settings={'history_width_px': preferred})
        errors = []
        app.report_callback_exception = lambda kind, value, trace: errors.append(str(value))
        try:
            for title in (
                '◆ Weekend museum visit: public transit, opening hours and a nearby lunch spot',
                '◆ Comparing indoor plants for a shaded apartment',
                '◇ Creating an illustrated travel journal',
                '◆ Planning a family movie night and a short playlist',
                *[f'◆ Synthetic conversation {number}: reading and project notes' for number in range(5, 31)],
            ):
                panel.session_list.insert('end', title)
            panel._trace_blocks, panel._trace_flush_after = [], None
            panel.chat_insert('You\n', 'you')
            panel.chat_insert('Help me plan a weekend museum visit using public transit.\n\n')
            panel.chat_insert('Nice\n', 'assistant')
            panel.chat_insert('I can compare the opening hours, route options and nearby lunch spots. '
                              'This preview contains only harmless synthetic conversation text.\n\n')
            block = panel.create_trace_block('thinking', 'Thinking', collapsed=False,
                                             initial='Compare travel time, opening hours and accessibility.\nCheck the remaining time for lunch.')
            block['resizer']._portalai_resize_rows(4)
            panel.chat_insert('\nDrag the gold divider to give history more room. '
                              'The gold horizontal scrollbar reveals each full conversation title.\n')
            panel.chat_zoom.set_percent(zoom)
            deadline = time.monotonic() + .6
            while time.monotonic() < deadline:
                app.update(); time.sleep(.01)
            panel.chat.yview_moveto(0)
            report['screenshots'].append(capture_window(app, artifacts.path(f'chat-layout-{name}.png')))
            if errors: raise RuntimeError('; '.join(errors))
        finally:
            panel.chat_layout.close(); panel.chat_zoom.close(); finish_tk_fixture(app)
    artifacts.path('chat-layout-visuals.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
