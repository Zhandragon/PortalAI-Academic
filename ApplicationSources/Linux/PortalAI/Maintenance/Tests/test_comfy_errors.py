"""Backend failure evidence survives without guessing, leaking inputs or replaying."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter')]
from comfy_errors import ComfyExecutionError, execution_failure, tool_failure
from comfy_bridge import ComfyBridge


def status(message='hostbuf_file_reader_read failed', **extra):
    return {'status_str':'error','messages':[['execution_error',{
        'node_id':'116:85','node_type':'KSamplerAdvanced','exception_type':'RuntimeError',
        'exception_message':message, 'traceback':['model_management.py: read_tensor_file_slice_into',
                                               'host_buffer.py: read_file_to_device'], **extra}]]}


class ComfyFailureTests(unittest.TestCase):
    def test_hostbuf_failure_identifies_subsystem_without_claiming_oom_or_corruption(self):
        for message in ('hostbuf_file_reader_read failed\n','HostBuffer.read_file_slice failed'):
            error=execution_failure('fixture',status(message))
            result=tool_failure('dialogue-video',error)
            self.assertFalse(result['success'])
            self.assertIn('not the input-image decoder',result['error'])
            self.assertIn('underlying cause is unconfirmed',result['error'])
            self.assertEqual(result['diagnostics']['error_category'],'model_weight_transfer')
            self.assertEqual(result['diagnostics']['node_type'],'KSamplerAdvanced')
            self.assertFalse(result['diagnostics']['automatic_retry'])
            from chat_evidence import project
            view=project({'name':'media_tool','content':json.dumps(result)},8,600)
            self.assertIn('model-weight transfer failed (not image decoding)',view)

    def test_image_decode_and_unknown_errors_are_not_misclassified(self):
        error=execution_failure('fixture',status('cannot identify image file',node_type='LoadImage'))
        self.assertEqual(error.diagnostics['error_category'],'comfy_execution')
        self.assertNotIn('not the input-image decoder',str(error))
        self.assertEqual(tool_failure('video',ValueError('bad argument')),
                         {'success':False,'tool':'video','error':'bad argument'})

    def test_evidence_is_bounded_and_excludes_workflow_inputs(self):
        row=status('tensor('*100000,traceback=['trace '*10000]*100,
                   current_inputs={'prompt':'DO NOT COPY THIS INPUT'},current_outputs=['PRIVATE OUTPUT'])
        before=copy.deepcopy(row)
        result=tool_failure('video',execution_failure('fixture',row))
        self.assertLess(len(json.dumps(result)),8000)
        self.assertNotIn('DO NOT COPY',json.dumps(result));self.assertNotIn('PRIVATE OUTPUT',json.dumps(result))
        self.assertFalse(result['diagnostics']['traceback_complete'])
        self.assertEqual(row,before)

    def test_latest_failure_and_missing_payload_remain_explicit(self):
        row=status();row['messages'].extend([None,['execution_cached',{}],['execution_error',{'message':'latest failure'}]])
        self.assertIn('latest failure',str(execution_failure('fixture',row)))
        self.assertIn('no execution_error details',str(execution_failure('fixture',{})))

    def test_wait_keeps_node_and_traceback_without_interrupt_or_requeue(self):
        bridge=ComfyBridge.__new__(ComfyBridge)
        bridge.base='http://fixture';bridge.ccfg={};bridge.interrupt=Mock();bridge.queue=Mock()
        with patch('comfy_bridge.require_space'),patch('comfy_bridge.http_json',return_value={'fixture':{'status':status()}}) as read:
            with self.assertRaises(ComfyExecutionError) as caught:bridge.wait('fixture')
        self.assertIn('host_buffer.py',caught.exception.diagnostics['traceback'][-1])
        self.assertEqual(read.call_count,1);self.assertEqual(read.call_args.args[0],'GET')
        bridge.queue.assert_not_called();bridge.interrupt.assert_not_called()

    def test_successful_history_remains_successful(self):
        bridge=ComfyBridge.__new__(ComfyBridge);bridge.base='http://fixture';bridge.ccfg={}
        entry={'status':{'completed':True,'status_str':'success'},'outputs':{}}
        with patch('comfy_bridge.require_space'),patch('comfy_bridge.http_json',return_value={'fixture':entry}):
            self.assertIs(bridge.wait('fixture'),entry)

    def test_cli_emits_diagnostics_and_failure_exit(self):
        import ai_tools as cli
        failure=execution_failure('fixture',status())
        with ExitStack() as stack:
            for name,replacement in (
                ('sys.argv',['ai_tools.py','version']),
                ('effort_policy.apply_tool_environment',lambda args,*a,**k:args),
                ('workload_compatibility.require_workload',Mock()),
                ('profile_tool_hydration.prepare_tool_files',Mock()),
            ):stack.enter_context(patch(name,replacement))
            stack.enter_context(patch.object(cli,'load_config',return_value={}))
            stack.enter_context(patch.object(cli,'version_metadata',side_effect=failure))
            emit=stack.enter_context(patch.object(cli,'emit',side_effect=SystemExit(1)))
            with self.assertRaises(SystemExit) as caught:cli.main()
        self.assertEqual(caught.exception.code,1);self.assertEqual(emit.call_args.args[1],1)
        self.assertEqual(emit.call_args.args[0]['diagnostics']['error_category'],'model_weight_transfer')


if __name__=='__main__':unittest.main()
