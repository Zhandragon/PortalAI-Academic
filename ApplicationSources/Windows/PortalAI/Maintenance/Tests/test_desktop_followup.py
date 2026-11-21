import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'ControlCenter'))
from task_progress import promised_desktop_action,inspection


class DesktopFollowupTests(unittest.TestCase):
    def test_unexecuted_desktop_plan_can_request_another_inference(self):
        self.assertTrue(promised_desktop_action('I will click the Slippi icon. Let me proceed.',[{'role':'tool','name':'computer'}],0))

    def test_no_new_permission_or_uncertain_effect_retry(self):
        rows=[{'role':'tool','name':'computer','execution':{'effectful':True,'outcome':'uncertain'}}]
        self.assertFalse(promised_desktop_action('I will click the icon.',rows,0))
        for text in ('I will click after your approval.','The launcher is open.','If you want, I will open it.'):
            self.assertFalse(promised_desktop_action(text,[{'role':'tool','name':'computer'}],0))
        self.assertFalse(promised_desktop_action('I will open it.',[],0))

    def test_observations_are_inspection_not_completed_task_steps(self):
        self.assertTrue(inspection('computer',{'action':'state'}))
        self.assertTrue(inspection('portal_ui',{'action':'state'}))
        self.assertFalse(inspection('computer',{'action':'click_element'}))


if __name__=='__main__':unittest.main()
