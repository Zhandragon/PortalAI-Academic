"""Voice choice and integrity regressions for Nice's English male preset."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / p) for p in ('Agent', 'ControlCenter')]
import tts_policy as policy
from piper_worker import verify_model
from chat_voice import VoiceIO


class NiceVoiceTests(unittest.TestCase):
    def test_preset_requires_its_own_files_and_preserves_default(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            hw = {'system': 'Windows', 'machine': 'AMD64', 'gpus': [], 'ram_available_bytes': 4*policy.GIB}
            def plan(voice=None):
                return policy.tts_plan(root, 'piper', hardware=hw, policy={}, voice=voice)
            for name in (policy.PIPER_MODEL, policy.PIPER_MODEL+'.json',
                         'Voice/Piper/packages/piper/__init__.py', 'Voice/Piper/packages/onnxruntime/__init__.py'):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'test')
            self.assertEqual(plan()['voice'], 'en_US-ljspeech-medium')
            with self.assertRaisesRegex(RuntimeError, 'incomplete'): plan(policy.NICE_VOICE)
            for name in (policy.PIPER_VOICES[policy.NICE_VOICE], policy.PIPER_VOICES[policy.NICE_VOICE]+'.json'):
                (root/name).write_bytes(b'test')
            self.assertEqual(plan(policy.NICE_VOICE)['voice'], policy.NICE_VOICE)
            with self.assertRaises(ValueError): plan('../../outside')

    def test_selected_integrity_needs_model_and_config_but_not_other_voices(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);model=root/policy.PIPER_VOICES[policy.NICE_VOICE]
            model.parent.mkdir(parents=True);pins=[]
            for p in (model,Path(str(model)+'.json')):
                p.write_bytes(b'fixture');pins.append({'dest':p.relative_to(root).as_posix(),'kind':'model',
                    'size':7,'sha256':hashlib.sha256(b'fixture').hexdigest()})
            lock={'assets':pins+[{'kind':'model','dest':policy.PIPER_MODEL,'size':1,'sha256':'unused'}]}
            verify_model(root,model,lock)
            with self.assertRaisesRegex(RuntimeError,'pin is missing'):verify_model(root,model,{'assets':pins[:1]})
            Path(str(model)+'.json').write_bytes(b'changed')
            with self.assertRaisesRegex(RuntimeError,'integrity'):verify_model(root,model,lock)

    def test_nice_selects_male_voice_and_brightens_pitch(self):
        with tempfile.TemporaryDirectory() as folder:
            voice=VoiceIO(folder,lambda:None);path=Path(folder)/'reply.wav'
            with patch('nice_voice.available',return_value=False), patch('piper_bridge.output_path',return_value=path), \
                 patch('piper_bridge.synthesize',return_value={'files':[str(path)]}) as synth, \
                 patch.object(voice,'_stage',side_effect=lambda name,admit,operation,**kw:operation(lambda:None)), \
                 patch.object(voice,'play') as play:
                voice.speak('Hello there.')
            self.assertEqual(synth.call_args.kwargs['voice'], policy.NICE_VOICE)
            self.assertEqual(play.call_args.kwargs['pitch_semitones'],2.0)

    def test_expressive_voice_owns_handoff_and_keeps_natural_pitch(self):
        with tempfile.TemporaryDirectory() as folder:
            voice=VoiceIO(folder,lambda:None);path=Path(folder)/'reply.wav'
            with patch('nice_voice.available',return_value=True),patch('piper_bridge.output_path',return_value=path), \
                 patch('nice_voice.synthesize',return_value={'files':[str(path)]}) as synth, \
                 patch.object(voice,'_stage',side_effect=lambda name,admit,operation,**kw:operation(lambda:None)) as stage, \
                 patch('piper_bridge.synthesize') as basic,patch.object(voice,'play') as play:
                voice.speak('We can face this together.')
            self.assertTrue(stage.call_args.kwargs['require_handoff'])
            synth.assert_called_once();basic.assert_not_called()
            self.assertEqual(play.call_args.kwargs['pitch_semitones'],0)

    def test_expressive_failure_never_replays_in_basic_voice(self):
        with tempfile.TemporaryDirectory() as folder:
            voice=VoiceIO(folder,lambda:None);path=Path(folder)/'reply.wav'
            with patch('nice_voice.available',return_value=True),patch('piper_bridge.output_path',return_value=path), \
                 patch('nice_voice.synthesize',side_effect=RuntimeError('worker failed')), \
                 patch.object(voice,'_stage',side_effect=lambda name,admit,operation,**kw:operation(lambda:None)), \
                 patch('piper_bridge.synthesize') as basic:
                with self.assertRaisesRegex(RuntimeError,'worker failed'):voice.speak('Hello.')
            basic.assert_not_called()

    def test_invalid_pitch_does_not_launch_player(self):
        voice=VoiceIO(ROOT,lambda:None)
        for value in (float('nan'),float('inf'),4,-4):
            with patch('chat_voice.subprocess.Popen') as launch:
                with self.assertRaises(ValueError):voice.play('unused.wav',pitch_semitones=value)
                launch.assert_not_called()


if __name__=='__main__':unittest.main()
