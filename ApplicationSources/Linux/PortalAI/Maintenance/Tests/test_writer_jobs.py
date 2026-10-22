import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'ControlCenter'))
from writer_jobs import WriterJobs


class WriterJobsTests(unittest.TestCase):
    def test_timeout_cannot_claim_stopped_then_completion_can(self):
        group = WriterJobs(); ready = threading.Event(); release = threading.Event()
        thread = group.thread(target=lambda: (ready.set(), release.wait(3)), name='writer')
        thread.start(); self.assertTrue(ready.wait(1)); group.close()
        try:
            self.assertEqual(group.wait(.01), {'stopped': False, 'remaining': ['writer']})
        finally:
            release.set(); thread.join(2)
        self.assertTrue(group.wait(1)['stopped'])

    def test_thread_created_before_close_cannot_start_after_close(self):
        group = WriterJobs(); ran = threading.Event()
        thread = group.thread(target=ran.set); group.close()
        with self.assertRaises(RuntimeError): thread.start()
        self.assertFalse(ran.is_set()); self.assertTrue(group.wait()['stopped'])

    def test_positive_receipt_requires_gate_closed(self):
        with self.assertRaises(RuntimeError): WriterJobs().wait()

    def test_current_writer_cannot_count_itself_as_quiescent(self):
        group = WriterJobs(); receipts = []
        def action():
            group.close(); receipts.append(group.wait(0))
        thread = group.thread(target=action, name='self'); thread.start(); thread.join(2)
        self.assertFalse(receipts[0]['stopped'])
        self.assertTrue(group.wait()['stopped'])


if __name__ == '__main__': unittest.main()
