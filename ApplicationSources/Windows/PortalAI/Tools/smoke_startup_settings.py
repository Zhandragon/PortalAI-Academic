"""Actual Controls/Settings widgets on a disposable account; model helper is simulated."""
import argparse
import json
from pathlib import Path
import sys
import threading
import time
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/p) for p in ('Tools', 'ControlCenter', 'Agent')]
from validation_artifacts import ValidationArtifacts
from smoke_login_continuity import run
from capture_page_fixture import capture_page
from smoke_account_panels import capture_window


def inspect(built, app, destination):
    root = built['root']; page = built['settings_page']
    if root == ROOT or not root.is_relative_to(destination):raise RuntimeError('Disposable fixture required')
    import settings_page
    from bundle_inventory import inventory
    policy = json.loads((root/'Agent/hardware_profiles.json').read_text())
    policy.update(selection='auto',variant_preference='standard')
    (root/'Agent/hardware_profiles.json').write_text(json.dumps(policy))
    for model in policy['models']:
        for key in ('path', 'projector'):
            if model.get(key):
                path = root/model[key];path.parent.mkdir(parents=True, exist_ok=True);path.write_bytes(b'synthetic model fixture')
    launcher = root/'Launchers/Start_PortableAI_Native_v15_133.py'
    launcher.parent.mkdir();launcher.write_text('# Placeholder; never executed')
    page.refresh_saved(inventory(root)['models'])
    wanted = 'qwen4-abliterated-q4'
    page.variables['selection'].set(next(label for label, value in page.model_ids.items() if value == wanted))
    page.variables['variant_preference'].set('uncensored')
    page.variables['voice_engine'].set('piper')
    assert 'Pending' in built['control_policy'].get()
    assert 'Abliterated' in built['control_policy'].get()
    built['show_tab']('controls');app.update()
    ready = threading.Event();release = threading.Event();threads = [];calls = []
    heartbeat = []
    def thread(**kwargs):
        result = threading.Thread(**kwargs);threads.append(result);return result
    class Child:
        returncode = 0
        def __init__(self, args, **kwargs):
            self.args = args;calls.append(args)
            from runtime_policy import load_effective_policy
            saved = load_effective_policy(root)
            assert saved['selection'] == wanted
            assert saved['variant_preference'] == 'uncensored'
            assert json.loads((root/'Agent/hardware_profiles.json').read_text())['variant_preference'] == 'standard'
            assert saved.get('media', {}).get('voice_engine', 'auto') == 'auto'
            self.requested = float(args[args.index('--requested-at')+1])
        def communicate(self, timeout=None):
            ready.set()
            if not release.wait(8):raise TimeoutError('Fixture helper hold timed out')
            return json.dumps({'started_at':self.requested,'success':True,
                              'qwen':{'model':{'id':wanted,'label':'Qwen 3 4B Abliterated Q4_K_M', 'context_tokens':8192}}}), ''
    def pump_until(predicate):
        end = time.monotonic()+8
        while not predicate():
            if time.monotonic()>end:
                raise TimeoutError('Controls fixture timed out: '+str({
                    'controls_width':built['ctl'].winfo_width(),'row_width':built['btnrow'].winfo_width(),
                    'menu_compact':built['portal_control_menu'].compact,'layout':built['layout_state']}))
            app.update();time.sleep(.01)
    try:
        with patch.object(built['gui_jobs'], 'thread', side_effect=thread), \
             patch('subprocess.Popen', side_effect=Child), \
             patch.object(built['native_chat_panel'].effort, 'refresh_capabilities'):
            built['startup_button'].invoke()
            pump_until(ready.is_set)
            assert page._busy and built['startup_button'].instate(['disabled'])
            built['start_components']()  # tray/compact command cannot queue a duplicate
            app.after(10, lambda: heartbeat.append(True))
            pump_until(lambda: bool(heartbeat))
            assert len(calls) == 1
            assert page.dirty('media') and not page.dirty('chat')
            release.set()
            pump_until(lambda: not page._busy)
            assert 'READY' in built['control_progress'].get()
            assert '4B Abliterated' in built['control_progress'].get()
            assert '4B Abliterated' in built['control_loaded'].get() and '8192' in built['control_loaded'].get()
            assert not built['startup_button'].instate(['disabled'])
        built['show_tab']('settings');app.update()
        capture_window(app,destination/'settings-first-pass.png')
        built['show_tab']('controls')
        built['page_watermark'].refresh();app.update()
        capture_page(app,built['page_watermark'],destination/'controls-selected-model.png')
        geometry = app.geometry()
        app.geometry('560x780+40+40');app.update()
        pump_until(lambda: built['portal_control_menu'].compact)
        app.update()
        for label in built['control_text_labels']:
            assert int(label.cget('wraplength')) <= built['ctl'].winfo_width()-20
        assert built['portal_control_menu'].menu_button.winfo_ismapped()
        assert len(built['portal_control_menu'].buttons) == 6
        # Narrow layouts intentionally hide the optional watermark window.
        capture_window(app,destination/'controls-narrow.png')
        app.geometry(geometry);app.update()
        pump_until(lambda: not built['portal_control_menu'].compact and all(button.winfo_ismapped() for button in built['buttons']))
        # Failed saves must never launch, including the direct compact/tray route.
        page.variables['backend'].set('cpu')
        with patch.object(settings_page, 'save_settings', side_effect=PermissionError('Synthetic save denied')), \
             patch('subprocess.Popen') as launch:
            built['start_components']()
            launch.assert_not_called()
        assert page.dirty('chat') and 'Synthetic save denied' in built['control_progress'].get()
        app.update();capture_page(app,built['page_watermark'],destination/'settings-save-failure.png')
        (destination/'controls-checks.json').write_text(json.dumps({
            'passed':True,'actual_controls_callbacks':True,'real_disposable_account_save':True,
            'model_helper_simulated':True,'selected_model':wanted,'duplicate_start_prevented':True,
            'tk_heartbeat_during_startup':bool(heartbeat),'media_draft_preserved':True,
            'personal_variant_saved':True,'shared_policy_unchanged':True,
            'failed_save_prevented_launch':True,'exact_model_in_completion':True},indent=2))
    finally:
        release.set()
        for worker in threads:worker.join(10)


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--artifacts-dir',required=True)
    args=parser.parse_args();artifacts=ValidationArtifacts(ROOT,args.artifacts_dir)
    try:report=run(artifacts.path(),inspector=inspect)
    except Exception as exc:report={'passed':False,'error':str(exc)}
    artifacts.path('startup-settings-smoke.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report));raise SystemExit(0 if report.get('passed') else 1)
