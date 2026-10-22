"""Public help must describe real routes without loading/probing private workloads."""
from contextlib import ExitStack, redirect_stdout
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'Agent')]
import ai_tools
import runtime_policy
import service_manager as services
from radeon_edit import uses_radeon


class GuidanceMetadataTests(unittest.TestCase):
    def quiet_routes(self):
        stack = ExitStack()
        for module, name in ((runtime_policy, 'detect_hardware'), (services, 'tool_plan'),
                             (services, 'port_open'), (services, '_active_science_activities'),
                             (ai_tools, 'service_start'), (ai_tools, 'service_status'),
                             (ai_tools.subprocess, 'Popen')):
            stack.enter_context(patch.object(module, name, side_effect=AssertionError('Metadata accessed ' + name)))
        return stack

    def cli(self, *arguments):
        output = io.StringIO()
        with self.quiet_routes(), patch.object(sys, 'argv', ['ai_tools.py', *arguments]), redirect_stdout(output):
            with self.assertRaises(SystemExit) as stopped:
                ai_tools.main()
        self.assertEqual(stopped.exception.code, 0)
        return output.getvalue()

    def test_version_is_process_and_hardware_probe_free(self):
        result = json.loads(self.cli('version'))
        self.assertTrue(result['success'])
        self.assertFalse(result['hardware_probed'])
        self.assertFalse(result['science_lifecycle']['activity_checked'])
        self.assertIsNone(result['science_lifecycle']['active'])
        self.assertIn('opencl', result['science_lifecycle']['gpu_policy'])
        self.assertNotIn('CIM', result['worker_launcher'])
        self.assertNotIn('Win32_Process', result['worker_launcher'])
        self.assertIn('Physical Radeon and Linux GPU validation remains pending', result['validation'])

    def test_platform_metadata_does_not_claim_an_unavailable_launcher(self):
        with self.quiet_routes():
            windows = services.launcher_metadata('Windows')
            linux = services.launcher_metadata('Linux')
            other = services.launcher_metadata('Darwin')
        self.assertIn('CREATE_NO_WINDOW', windows['worker_launcher'])
        self.assertIn('Linux executable', linux['worker_launcher'])
        self.assertNotIn('CREATE_NO_WINDOW', linux['worker_launcher'])
        self.assertTrue('No packaged' in other['worker_launcher'] or 'owned macOS process group' in other['worker_launcher'])
        self.assertNotIn('CREATE_NO_WINDOW', other['worker_launcher'])

    def test_version_distinguishes_scaled_routes_and_cpu_limits(self):
        with self.quiet_routes():
            result = ai_tools.version_metadata()
        for backend in ('14B Windows/CUDA', '1.3B Radeon/Linux'):
            self.assertIn(backend, result['video_edit_backend'])
        # Linux CUDA also takes the scaled video/edit route; it is not 14B-only.
        self.assertTrue(uses_radeon({'system': 'Linux', 'gpus': [{'index': 0, 'backend': 'cuda'}]}))
        self.assertFalse(uses_radeon({'system': 'Windows', 'gpus': [{'index': 0, 'backend': 'cuda'}]}))
        self.assertIn('Qwen3-TTS ROCm', result['voice_backends'])
        self.assertIn('Piper CPU basic English speech', result['voice_backends'])
        self.assertIn('voice cloning/design', result['unsupported_cpu_media'])
        self.assertIn('SD1.5/native-CPU', result['image_backends']['generation'])
        self.assertNotIn('video-small', result['unsupported_cpu_media'])

    def test_help_routes_include_scaled_editing_and_small_commands(self):
        output = self.cli('--help')
        for word in ('InstructPix2Pix', 'VACE 1.3B', 'voice-say', 'video-small'):
            self.assertIn(word, output)
        image = self.cli('image', '--help')
        self.assertIn('Windows/Linux', image)
        video = self.cli('video-edit', '--help')
        self.assertIn('17 frames', video)
        self.assertIn('20 steps', video)

    def test_vision_help_explains_frontend_requirement(self):
        output = self.cli('video-understand', '--help')
        flattened = ' '.join(output.split())
        self.assertIn('host requires a frontend image reader', flattened)
        self.assertIn('Native Chat should select qwen', flattened)
        self.assertIn('requires an admitted vision model', flattened)
        self.assertNotIn('OpenGUI', flattened)

    def test_service_science_status_still_reports_real_activity(self):
        active = [{'pid': 321, 'compute': 'opencl'}]
        with patch.object(services, '_active_science_activities', return_value=active) as inspect:
            result = services.status('science')['science']
        inspect.assert_called_once_with()
        self.assertTrue(result['activity_checked'])
        self.assertTrue(result['active'])
        self.assertEqual(result['active_count'], 1)
        self.assertEqual(result['activities'], active)


if __name__ == '__main__':
    unittest.main()
