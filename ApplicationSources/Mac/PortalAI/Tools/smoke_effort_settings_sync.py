"""Real bidirectional chat/Settings controls with disposable accounts and dummy weights."""
import argparse
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/p) for p in ('Tools', 'ControlCenter', 'Agent')]
from validation_artifacts import ValidationArtifacts
from smoke_login_continuity import run
from smoke_account_panels import capture_window


def inspect(built, app, destination):
    from runtime_policy import load_effective_policy
    from bundle_inventory import inventory
    from effort_policy import load_preferences
    root = built['root']; page = built['settings_page']; panel = built['native_chat_panel']; control = panel.effort
    if root == ROOT or not root.is_relative_to(destination): raise RuntimeError('Disposable root required')
    policy_path = root/'Agent/hardware_profiles.json'; baseline = policy_path.read_bytes()
    policy = json.loads(baseline)
    for model in policy['models']:
        for key in ('path', 'projector'):
            if model.get(key):
                path = root/model[key]; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'Synthetic fixture; never load as a model')
    page.refresh_saved(inventory(root)['models'])
    checks = []
    def verify(model, level, variant):
        cfg = load_effective_policy(root)
        assert (cfg['selection'], cfg['variant_preference']) == (model, variant), cfg['selection']
        assert page.values('chat')['selection'] == model
        assert page.variables['variant_preference'].get() == variant
        assert control.profile == load_preferences(root)['chat'] == level
        assert control.uncensored.get() == (variant == 'uncensored')
        assert int(control.scale.get()) == ('fast', 'balanced', 'deep').index(level)
        assert not page._dirty.intersection(('selection', 'variant_preference'))
        checks.append({'model': model, 'effort': level, 'variant': variant})
    def choose(key, value):
        if key == 'selection': value = next(k for k, v in page.model_ids.items() if v == value)
        page.variables[key].set(value); page.selectors[key].event_generate('<<ComboboxSelected>>')
        app.update()
    with patch.object(control, 'refresh_capabilities'):
        control.capability_data = None
        # Keep unrelated unsaved choices while the latest model control wins.
        page.variables['backend'].set('cpu'); page.variables['context_tokens'].set('4096')
        page.variables['voice_engine'].set('piper')
        control._changed('0'); verify('qwen1.7-abliterated-q8', 'fast', 'uncensored')
        control.variant_check.invoke(); verify('qwen1.7-q8', 'fast', 'standard')
        control._changed('1'); verify('qwen4-q4', 'balanced', 'standard')
        choose('selection', 'qwen27-q4'); verify('qwen27-q4', 'deep', 'uncensored')
        choose('variant_preference', 'standard'); verify('qwen27-standard-q4', 'deep', 'standard')
        assert page.variables['backend'].get() == 'cpu' and page.variables['context_tokens'].get() == '4096'
        assert page.variables['voice_engine'].get() == 'piper'
        saved = load_effective_policy(root)
        assert saved['backend'] == policy['backend'] and saved['context_tokens'] == policy['context_tokens']
        assert saved.get('media', {}).get('voice_engine', 'auto') != 'piper'
        old_plan = control.active_plan = {'profile': 'deep', 'fixture': True}
        panel.busy = True
        try:
            control._changed('0')
            choose('selection', 'qwen1.7-q8')
            control.sync_saved_choice()
            assert control.active_plan is old_plan
            verify('qwen27-standard-q4', 'deep', 'standard')
        finally: panel.busy = False
        control._changed('0'); verify('qwen1.7-q8', 'fast', 'standard')
        control.receive_capabilities({'serial': control._probe_serial-1, 'result': {'error': 'stale'}})
        assert not control.capability_data or control.capability_data.get('error') != 'stale'
        for theme in ('light', 'dark'):
            if theme == 'dark': built['toggle_theme']()
            for width in (972, 720):
                control.capability_data = {'profiles': {'fast': {
                    'selection': 'qwen1.7-q8', 'available': True, 'can_apply': True}}}
                control._render()
                app.geometry(f'{width}x820+30+30'); built['show_tab']('chat')
                until = time.monotonic()+.25
                while time.monotonic() < until: app.update(); time.sleep(.01)
                assert control.variant_check.winfo_ismapped()
                assert control.variant_check.winfo_rootx()+control.variant_check.winfo_width() <= app.winfo_rootx()+app.winfo_width()
                assert control.variant_check.winfo_rooty()+control.variant_check.winfo_height() <= app.winfo_rooty()+app.winfo_height()
                capture_window(app, destination/f'effort-{theme}-{width}.png')
        built['toggle_theme'](); app.update()
    assert policy_path.read_bytes() == baseline, 'Personal choices modified shared hardware policy'
    (destination/'sync.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--artifacts-dir', required=True)
    args = parser.parse_args(); artifacts = ValidationArtifacts(ROOT, args.artifacts_dir)
    try: report = run(artifacts.path(), inspector=inspect)
    except Exception as exc: report = {'passed': False, 'error': str(exc)}
    artifacts.path('report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report)); raise SystemExit(not report.get('passed'))
