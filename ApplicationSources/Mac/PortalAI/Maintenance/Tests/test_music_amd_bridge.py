from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import music_amd_bridge as music
import workload_compatibility as compatibility


class MusicAMDTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.hw={'system':'Windows','machine':'AMD64','gpus':[],
                 'ram_available_bytes':24*music.GIB,'amd_gpu':{'available':True,'compute_ok':True,
                 'free_bytes':8*music.GIB,'shared_memory':False}}

    def test_nvidia_keeps_existing_service_and_amd_requires_real_compute(self):
        self.assertFalse(music.use_rocm({**self.hw,'gpus':[{'backend':'cuda','index':0}]}))
        self.assertTrue(music.use_rocm(self.hw))
        for command in ('music','score-video'):
            compatibility.require_workload(command,self.hw)
            compatibility.require_workload(command,{**self.hw,'amd_gpu':{'available':False}})
        # CPU routing is allowed through preflight; the explicit AMD plan still probes.
        with self.assertRaisesRegex(RuntimeError,'compute probe'):
            music.plan(self.root,{**self.hw,'amd_gpu':{'available':False}})

    def test_resource_checks_precede_import_or_model_load(self):
        with self.assertRaisesRegex(RuntimeError,'6 GiB'):
            music.plan(self.root,{**self.hw,'amd_gpu':{**self.hw['amd_gpu'],'free_bytes':5*music.GIB}})
        with self.assertRaisesRegex(RuntimeError,'20 GiB'):
            music.plan(self.root,{**self.hw,'ram_available_bytes':19*music.GIB,
                       'amd_gpu':{**self.hw['amd_gpu'],'shared_memory':True}})
        with self.assertRaisesRegex(RuntimeError,'12 GiB'):
            music.plan(self.root,{**self.hw,'ram_available_bytes':11*music.GIB})
        with self.assertRaisesRegex(RuntimeError,'dependency missing'):
            music.plan(self.root,self.hw)
        with self.assertRaisesRegex(RuntimeError,'compute probe'):
            music.plan(self.root,{**self.hw,'system':'Linux'})

    def test_invalid_requests_are_never_silently_truncated(self):
        for prompt,lyrics,duration,seed in [('', '',15,42),('x'*513,'',15,42),
            ('music','x'*4097,15,42),('music','',9,42),('music','',31,42),
            ('music','',float('nan'),42),('music','',15,-1)]:
            with self.assertRaises(ValueError):music.validate_request(prompt,lyrics,duration,seed)
        music.validate_request('music','lyrics',10,0)
        music.validate_request('music','lyrics',30,42)

    def test_child_arguments_preserve_lyrics_and_use_owned_staged_music_path(self):
        seen={}
        def run(profile,command,validate,**kwargs):
            seen.update(kwargs);seen['argv']=command(self.root/'Outputs/Music/test.part.flac')
            return {'files':['result.flac'],'engine':'acestep-rocm'}
        with patch.object(music,'run_generation',side_effect=run):
            result=music.generate({'backend':'rocm'},'A "literal" prompt','[Verse]\nhello',15,False,52,self.root)
        self.assertEqual(seen['kind'],'music')
        self.assertIn('[Verse]\nhello',seen['argv']);self.assertIn('utf8',seen['argv'])
        self.assertNotIn('--instrumental',seen['argv'])
        self.assertEqual(result['physical_radeon_validation'],'pending')


if __name__=='__main__':unittest.main()
