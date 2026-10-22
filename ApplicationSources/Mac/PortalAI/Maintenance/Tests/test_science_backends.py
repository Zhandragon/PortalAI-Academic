from argparse import Namespace
import ast
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/"Agent"),str(ROOT)]
from Scientific.science_core import _openmm_platform
from ai_tools import _science_execution_profile
import service_manager as sm


class ScienceBackendTests(unittest.TestCase):
    def test_default_never_selects_unleased_gpu(self):
        mm=Mock()
        for p in ({},{"platform":"auto"},{"platform":"cpu"}):
            _openmm_platform(p,mm)
            mm.Platform.getPlatformByName.assert_called_with("CPU")

    def test_opencl_is_explicit_and_single_device(self):
        mm=Mock();platform,props=_openmm_platform({"platform":"opencl","device_index":1},mm)
        mm.Platform.getPlatformByName.assert_called_with("OpenCL")
        self.assertEqual(props,{"DeviceIndex":"1","Precision":"mixed"})
        for value in (-1,"0,1",True):
            with self.assertRaises(ValueError):_openmm_platform({"platform":"opencl","device_index":value},mm)
        with self.assertRaises(ValueError):_openmm_platform({"platform":"invalid"},mm)

    def test_cli_profile_routes_opencl_through_gpu_lease(self):
        args=Namespace(operation="protein.minimize",set=["platform=opencl"],json=None,file=None)
        self.assertEqual(_science_execution_profile(args),{"gpu_requested":True,"gpu_backend":"openmm-opencl","compute":"opencl"})
        args.set=[]
        self.assertFalse(_science_execution_profile(args)["gpu_requested"])

    def test_opencl_failure_still_restores_chat_and_releases_lease(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with patch.object(sm,"root_dir",return_value=root), patch.object(sm,"_science_activity_path",return_value=root/"science.json"), \
                 patch.object(sm,"acquire_gpu_lease",return_value="lease") as acquire, patch.object(sm,"quiesce_gpu_workers"), \
                 patch.object(sm,"qwen_gpu_handoff_begin",return_value={"active":True}) as begin, \
                 patch.object(sm,"qwen_gpu_handoff_end") as restore, patch.object(sm,"release_gpu_lease") as release:
                with self.assertRaisesRegex(RuntimeError,"device failed"):
                    with sm.science_workload("protein.minimize",gpu_requested=True,gpu_backend="openmm-opencl") as p:
                        self.assertEqual(p["compute"],"opencl")
                        raise RuntimeError("device failed")
                restore.assert_called_once_with({"active":True});release.assert_called_once_with("lease")
                self.assertIn("openmm-opencl",acquire.call_args.args[0])
                self.assertFalse((root/"science.json").exists())

    def test_all_request_encodings_choose_the_same_leased_backend(self):
        import scientific_tool_bridge as bridge
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'request.json'
            for backend in ('auto','cpu','opencl','cuda'):
                for key in ('platform','device'):
                    payload={key:backend,'device_index':0,'tolerance_kj_mol_nm':0.0001}
                    path.write_text(json.dumps(payload))
                    sources=({'set':[key+'='+backend]}, {'json':json.dumps(payload)}, {'file':str(path)})
                    for source in sources:
                        args=Namespace(operation='protein.minimize',**{'set':None,'json':None,'file':None,**source})
                        with patch('media_paths.media_reference',return_value=path):
                            profile=_science_execution_profile(args)
                        self.assertEqual(profile['gpu_requested'],backend in ('cuda','opencl'))
                        self.assertEqual(profile['compute'],backend if backend in ('cuda','opencl') else 'cpu')
            with self.assertRaises(ValueError):
                _science_execution_profile(Namespace(operation='protein.minimize',set=['platform=cpu'],json='{"platform":"cuda"}',file=None))

    def test_execution_uses_the_payload_admitted_before_waiting_for_lease(self):
        import ai_tools
        import scientific_tool_bridge as bridge
        tree=ast.parse((ROOT/'Agent/ai_tools.py').read_text(encoding='utf-8-sig'))
        node=next(n for n in ast.walk(tree) if isinstance(n,ast.If) and ast.unparse(n.test)=="args.cmd == 'science'"
                  and any(isinstance(x,ast.With) for x in n.body))
        # Replace only the branch's trailing return so the actual dispatch body
        # can be exercised without running unrelated CLI or model startup code.
        node.body=[n for n in node.body if not isinstance(n,ast.Return)]
        for before,after in (('cpu','cuda'),('opencl','cpu')):
            with tempfile.TemporaryDirectory() as d:
                path=Path(d)/'request.json'
                payload={'platform':before,'device_index':0,'tolerance_kj_mol_nm':0.000123,'max_iterations':17}
                path.write_text(json.dumps(payload))
                @contextmanager
                def workload(operation,**kwargs):
                    self.assertEqual(kwargs['gpu_requested'],before=='opencl')
                    path.write_text(json.dumps({**payload,'platform':after}))
                    yield {'compute':before}
                execute=Mock(return_value={'success':True})
                namespace={'args':Namespace(cmd='science',operation='protein.minimize',set=None,json=None,file=str(path),output_dir=None),
                           '_science_execution_profile':ai_tools._science_execution_profile,'science_workload':workload,
                           'run_science_request':execute,'json':json,'emit':Mock()}
                with patch('media_paths.media_reference',return_value=path) as resolve:
                    exec(compile(ast.Module(body=[node],type_ignores=[]),'science-dispatch','exec'),namespace)
                self.assertEqual(resolve.call_count,1)
                self.assertEqual(json.loads(execute.call_args.kwargs['json_text']),payload)
                self.assertNotIn('file',execute.call_args.kwargs)


if __name__=="__main__":unittest.main()
