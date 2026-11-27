"""Metrics preserve exceptions and serialized GPU cleanup without using a GPU."""
import ast
from contextlib import contextmanager
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
from media_timing import PhaseTimings
from comfy_bridge import ComfyBridge


class TimingTests(unittest.TestCase):
    def test_monotonic_phases_accumulate_and_preserve_failure(self):
        times=iter([1,3,5,8]);metrics=PhaseTimings(lambda:next(times))
        with metrics.phase('work'):pass
        with self.assertRaisesRegex(RuntimeError,'original failure'):
            with metrics.phase('work'):raise RuntimeError('original failure')
        self.assertEqual(metrics.snapshot(),{'work':5})

    def test_metrics_are_bounded_and_contain_no_paths_or_prompts(self):
        metrics=PhaseTimings()
        for n in range(32):
            with metrics.phase('phase_'+str(n)):pass
        with self.assertRaises(ValueError):
            with metrics.phase('extra'):pass
        with patch('sys.stderr',new_callable=io.StringIO) as stream:metrics.emit()
        row=json.loads(stream.getvalue().split(' ',1)[1])
        self.assertEqual(set(row),{'version','seconds'})
        self.assertLess(len(stream.getvalue()),2048)
        with patch('sys.stderr.write',side_effect=OSError('closed')):metrics.emit()

    def test_comfy_metrics_do_not_queue_or_wait_twice(self):
        bridge=ComfyBridge.__new__(ComfyBridge)
        bridge.queue=Mock(return_value='job');bridge.wait=Mock(return_value={'outputs':{}})
        bridge.fetch_outputs=Mock(return_value=['output.png'])
        result=bridge.run({'workflow':'fixture'},Path('.'))
        bridge.queue.assert_called_once();bridge.wait.assert_called_once_with('job')
        bridge.fetch_outputs.assert_called_once()
        self.assertEqual(result['files'],['output.png'])
        self.assertEqual(set(result['timings']),{'comfy_queue','comfy_wait','output_fetch'})
        self.assertIn('not isolated GPU',result['timing_scope'])

    def test_serialized_handoff_cleanup_and_original_exception_are_preserved(self):
        tree=ast.parse((ROOT/'Agent/ai_tools.py').read_text(encoding='utf-8-sig'))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_exclusive_gpu')
        events=[]
        def mark(name,value=None):
            def run(*a,**kw):events.append(name);return value
            return run
        namespace=dict(contextmanager=contextmanager,root_dir=lambda:ROOT,
            acquire_gpu_lease=mark('lease','lease-token'),quiesce_gpu_workers=mark('quiesce'),
            qwen_gpu_handoff_begin=mark('handoff','state'),service_stop=mark('stop'),
            _clear_gpu_state=mark('clear'),qwen_gpu_handoff_end=mark('restore'),release_gpu_lease=mark('release'))
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<fixture>','exec'),namespace)
        guard=Mock()
        with patch.dict(sys.modules,{'workload_request':SimpleNamespace(request_guard=lambda root:guard)}),patch.object(PhaseTimings,'emit') as emit:
            with self.assertRaisesRegex(RuntimeError,'render failure'):
                with namespace['_exclusive_gpu']('comfyui','image'):raise RuntimeError('render failure')
            emit.assert_called_once()
        self.assertEqual(events,['lease','quiesce','handoff','stop','clear','restore','release'])


if __name__=='__main__':unittest.main()
