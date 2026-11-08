"""Regression coverage for the actual native science result/dispatch boundary."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'Agent'), str(ROOT)]
import science_tools
from Scientific import world_scene


class ScienceChatContractTests(unittest.TestCase):
    def test_schema_survives_both_result_serialization_passes(self):
        description = world_scene.describe()
        # dispatch wraps the operation, then main serializes the entire reply.
        reply = science_tools._result('physics.world_schema', 'Schema', data=description)
        wire = json.loads(json.dumps(science_tools._json_safe(reply)))
        self.assertEqual(wire['data'], description)
        for example in wire['data']['examples'].values():
            world_scene.validate(example)

    def test_invalid_dimension_identifies_object_component_and_range(self):
        with self.assertRaisesRegex(ValueError, r'scene\.objects\[0\]\.size\[0\].*0\.1.*10.*12'):
            world_scene.validate({'objects': [{'size': [12, 1, 10]}]})

    def test_extra_scene_wrapper_explains_the_unknown_key(self):
        with self.assertRaisesRegex(ValueError, r'unknown fields.*scene'):
            world_scene.validate({'scene': {'objects': []}})

    def test_native_chat_can_calculate_a_voltage_divider(self):
        payload = {'elements': [
            {'type': 'V', 'name': 'V1', 'n1': 'in', 'n2': '0', 'value': 10},
            {'type': 'R', 'n1': 'in', 'n2': 'out', 'value': 1000},
            {'type': 'R', 'n1': 'out', 'n2': '0', 'value': 1000}]}
        with tempfile.TemporaryDirectory() as tmp, patch('scientific_tool_bridge._activate'), patch('profile_tool_hydration.prepare_tool_files') as hydrate:
            result = science_tools.dispatch(Path(tmp), Path(tmp), {'operation': 'electrical.dc', 'input': payload})
            hydrate.assert_called_once_with(Path(tmp), 'science', operation='electrical.dc')
        self.assertTrue(result['success'])
        self.assertAlmostEqual(result['data']['node_voltages_v']['out'], 5.0)
        self.assertAlmostEqual(result['data']['voltage_source_currents_a']['V1'], -0.005)

    def test_legacy_status_stays_on_legacy_route(self):
        with patch.object(science_tools, 'op_status', return_value={'legacy': True}):
            with patch('profile_tool_hydration.prepare_tool_files'):
                self.assertEqual(science_tools.dispatch(ROOT, ROOT, {'operation': 'status'}), {'legacy': True})

    def test_core_file_result_is_an_openable_chat_attachment(self):
        from Scientific import science_core
        with tempfile.TemporaryDirectory() as tmp, patch('scientific_tool_bridge._activate'), patch('profile_tool_hydration.prepare_tool_files'):
            path = Path(tmp) / 'molecule.svg'
            path.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            with patch.object(science_core, 'run_operation', return_value={'file': str(path), 'formula': 'C2H6O'}):
                result = science_tools.dispatch(Path(tmp), Path(tmp), {'operation': 'chem.render', 'input': {'smiles': 'CCO'}})
            self.assertEqual(result['files'], [str(path)])


if __name__ == '__main__':
    unittest.main()
