"""Warmup delivers real short-window history without speeding up inventory."""
from collections import deque
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter')]
from activity_monitor import TelemetryMonitor,ActivityCharts

class ClockStop:
    def __init__(self,end=41):self.now=0.;self.end=end;self.cancel=False;self.waits=[]
    def is_set(self):return self.cancel or self.now>=self.end
    def wait(self,delay):self.waits.append(delay);self.now+=delay;return self.is_set()

class TelemetryWarmupTests(unittest.TestCase):
    def test_fast_samples_taper_and_keep_latest_without_inventory_calls(self):
        clock=ClockStop();samples=[];sampler=Mock()
        sampler.sample.side_effect=lambda **kw:{'at':clock.now,'cpu':20,'ram':30}
        monitor=TelemetryMonitor(sampler,clock,samples.append,clock=lambda:clock.now)
        monitor.run()
        self.assertGreaterEqual(len([s for s in samples if s['at']<10]),20)
        self.assertEqual([s['at'] for s in samples if s['at']>=30],[30,35,40])
        self.assertEqual(sampler.sample.call_args.kwargs['gpu_interval'],15)
        sampler.close.assert_called_once()
        copy=monitor.latest();copy['cpu']=99
        self.assertEqual(monitor.latest()['cpu'],20)

    def test_stop_during_probe_discards_result_and_closes_counters(self):
        clock=ClockStop();published=Mock();sampler=Mock()
        def sample(**kw):clock.cancel=True;return {'at':0,'cpu':20}
        sampler.sample.side_effect=sample
        TelemetryMonitor(sampler,clock,published,clock=lambda:clock.now).run()
        published.assert_not_called();sampler.close.assert_called_once()

    def test_slow_or_failed_probe_never_creates_catchup_spin(self):
        clock=ClockStop(end=8);sampler=Mock()
        def sample(**kw):clock.now+=3;raise OSError('counter unavailable')
        sampler.sample.side_effect=sample
        TelemetryMonitor(sampler,clock,Mock(),clock=lambda:clock.now).run()
        self.assertEqual(sampler.sample.call_count,3)
        self.assertTrue(all(wait>=.1 for wait in clock.waits))
        sampler.close.assert_called_once()

    def test_ten_seconds_of_real_history_fills_width_without_backfill(self):
        canvas=Mock();canvas.winfo_width.return_value=200;canvas.winfo_height.return_value=62
        samples=deque([{'at':100,'cpu':0},{'at':110,'cpu':100}])
        chart=SimpleNamespace(palette={},canvases={'cpu':canvas},samples=samples,_started_at=100)
        ActivityCharts.redraw(chart)
        self.assertEqual(canvas.create_line.call_args.args,(2,59,198,3))
        self.assertEqual(len(samples),2)

    def test_cached_gpu_observations_are_not_duplicated(self):
        canvas=Mock();canvas.winfo_width.return_value=200;canvas.winfo_height.return_value=62
        chart=SimpleNamespace(palette={},canvases={'gpu':canvas},_started_at=100,
            samples=deque([{'at':100,'gpu_at':100,'gpu':0},{'at':100.5,'gpu_at':100,'gpu':0},
                           {'at':102,'gpu_at':102,'gpu':100}]))
        ActivityCharts.redraw(chart)
        self.assertEqual(canvas.create_line.call_args.args,(2,59,198,3))

if __name__=='__main__':unittest.main()
