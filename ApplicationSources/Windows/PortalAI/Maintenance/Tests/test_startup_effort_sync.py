"""Saved choices win; only a current Automatic startup supplies a display hint."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
import chat_selection
from chat_effort_ui import ChatEffortControls

MODELS=[{'id':name,'variant':'standard'} for name in ('qwen4-q4','qwen27-standard-q4')]

def controls():
    c=ChatEffortControls.__new__(ChatEffortControls)
    c.panel=SimpleNamespace(busy=False,root=ROOT)
    c.profile='balanced';c._choice_signature=None;c._automatic_model=None;c._probe_serial=0
    c.scale=Mock();c.uncensored=Mock();c._render=Mock();c.refresh_capabilities=Mock();c._sync_linked_voice=Mock()
    c._module=Mock(return_value=chat_selection)
    return c

class StartupEffortSyncTests(unittest.TestCase):
    def test_saved_27b_overrides_a_stale_balanced_effort_read(self):
        c=controls();policy={'selection':'qwen27-standard-q4','models':MODELS}
        c.sync_saved_choice(policy=policy,preferences={'chat':'balanced'})
        self.assertEqual(c.profile,'deep');c.scale.set.assert_called_with(2)
        # A no-change refresh also repairs display drift without saving settings.
        c.profile='balanced'
        c.sync_saved_choice(policy=policy,preferences={'chat':'balanced'})
        self.assertEqual(c.profile,'deep')

    def test_automatic_startup_updates_display_and_survives_monitor_refresh(self):
        c=controls();policy={'selection':'auto','models':MODELS,'_profile_id':'a'}
        c.sync_saved_choice(policy=policy,preferences={'chat':'balanced'},loaded_model=MODELS[1])
        self.assertEqual(c.profile,'deep');c.scale.set.assert_called_with(2)
        c._sync_linked_voice.assert_not_called()
        serial=c._probe_serial
        c.sync_saved_choice(policy=policy,preferences={'chat':'balanced'})
        self.assertEqual((c.profile,c._probe_serial),('deep',serial))
        self.assertEqual(policy['selection'],'auto')
        c.sync_saved_choice(policy={**policy,'_profile_id':'b'},preferences={'chat':'balanced'})
        self.assertEqual(c.profile,'balanced');self.assertIsNone(c._automatic_model)

    def test_later_saved_choice_wins_over_previous_loaded_model(self):
        c=controls()
        c.sync_saved_choice(policy={'selection':'qwen4-q4','models':MODELS},
                            preferences={'chat':'deep'},loaded_model=MODELS[1])
        self.assertEqual(c.profile,'balanced');self.assertIsNone(c._automatic_model)

    def test_automatic_label_keeps_actual_size_when_preview_is_locked(self):
        c=controls();c.profile='deep';c.active_plan=None;c._details=None;c.label=Mock()
        c.panel.settings={};c.panel.COL={'gold':'gold','cyan':'cyan'}
        c.capability_data={'profiles':{'deep':{'locked':True}}}
        c._automatic_model=((),MODELS[1],'deep')
        ChatEffortControls._render(c)
        self.assertEqual(c.label.configure.call_args.kwargs['text'],'Deep · 27B · Auto · locked')

    def test_busy_request_and_unknown_model_do_not_replace_effort(self):
        c=controls();c.panel.busy=True
        c.sync_saved_choice(policy={'selection':'auto','models':MODELS},preferences={'chat':'deep'},loaded_model=MODELS[1])
        self.assertEqual(c.profile,'balanced');c.scale.set.assert_not_called()
        c.panel.busy=False
        c.sync_saved_choice(policy={'selection':'auto','models':MODELS},preferences={'chat':'balanced'},loaded_model={'id':'unconfigured-27b'})
        self.assertEqual(c.profile,'balanced');self.assertIsNone(c._automatic_model)

if __name__=='__main__':unittest.main()
