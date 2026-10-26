"""Storage-fault diagnostics use injected writes, never live keys or profiles."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
from projection_worker import NativeStatusReporter


class NativeStatusTests(unittest.TestCase):
    def setUp(self):
        self.now=0.
        self.write=Mock();self.warning=Mock()
        self.path=Path('synthetic-native-status.json')
        self.report=NativeStatusReporter(self.path,self.write,self.warning,
            clock=lambda:self.now,wall_clock=lambda:1234.)

    def test_reconnect_phase_changes_do_not_bypass_write_budget(self):
        for i in range(300):
            self.now=i/10
            self.report(('connecting','authenticated','unavailable')[i%3])
        self.assertEqual(self.write.call_count,1)
        self.now=30.;self.report('standby')
        self.assertEqual(self.write.call_count,2)
        self.assertEqual(self.write.call_args.args[1]['state'],'standby')

    def test_steady_publishing_counts_all_acknowledgements_in_memory(self):
        for i in range(61):
            self.now=i*.5;self.report('publishing')
        self.assertEqual(self.write.call_count,2)
        self.assertEqual(self.write.call_args.args,(self.path,{
            'protocol':'portalai-native-state/2','state':'publishing',
            'updated_unix':1234.,'receiver_acknowledgements':61,
            'private_payloads_logged':False,'effects_performed':False}))

    def test_final_stopped_status_is_written_once_without_waiting(self):
        self.report('publishing');self.now=1.;self.report('stopped')
        self.assertEqual(self.write.call_count,2)
        self.assertEqual(self.write.call_args.args[1]['state'],'stopped')
        self.now=100.;self.report('stopped')
        self.assertEqual(self.write.call_count,2)

    def test_disk_error_latches_off_across_reconnect_and_shutdown(self):
        for error in (OSError(1117,'synthetic I/O failure'),ValueError('synthetic invalid write')):
            with self.subTest(error=type(error).__name__):
                self.setUp();self.write.side_effect=error
                self.report('publishing')
                for i,phase in enumerate(('unavailable','connecting','authenticated','publishing','stopped')):
                    self.now=(i+1)*60;self.report(phase)
                self.assertEqual(self.write.call_count,1)
                self.warning.assert_called_once_with()
                self.assertTrue(self.report.disabled)

    def test_warning_failure_cannot_restart_writes_or_abort_transport(self):
        self.write.side_effect=OSError('synthetic disk error')
        self.warning.side_effect=RuntimeError('synthetic display failure')
        self.report('publishing');self.now=60.;self.report('publishing')
        self.assertEqual(self.write.call_count,1)
        self.assertEqual(self.report.accepted,2)

    def test_new_worker_has_no_persisted_disable_flag(self):
        self.write.side_effect=OSError('synthetic disk error');self.report('connecting')
        fresh_write=Mock()
        fresh=NativeStatusReporter(self.path,fresh_write,self.warning)
        fresh('connecting');fresh_write.assert_called_once()


if __name__=='__main__':unittest.main()
