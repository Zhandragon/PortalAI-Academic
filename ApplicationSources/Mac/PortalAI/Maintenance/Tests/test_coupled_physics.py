"""Numerical invariants and output boundaries, with no production accounts."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT/'Maintenance/Validation/WorkbenchUI_20261010'
sys.path[:0] = [str(ROOT/('Runtime/ScientificPython/packages' if os.name == 'nt' else 'Runtime/LinuxPackages/science')), str(ROOT), str(ROOT/'Agent')]
import numpy as np
from Scientific.coupled_physics import CoupledDemo, settings, stress, contact
from Scientific.coupled_physics_tool import run
from Scientific.physics_viewer import document
from profile_paths import ProfileLocked


class PhysicsInvariants(unittest.TestCase):
    def test_settings_reject_nonfinite_or_unbounded_requests(self):
        for values in ({'dimensions':True}, {'dimensions':4}, {'grid':200}, {'frames':1000},
                       {'duration_s':float('nan')}, {'duration_s':float('inf')}, {'duration_s':10},
                       {'arbitrary_code':'bad'}, {'dimensions':3,'grid':40}):
            with self.subTest(values=values), self.assertRaises(ValueError): settings(values)

    def test_rest_and_rigid_rotation_have_no_elastic_stress(self):
        for d in (2,3):
            f = np.eye(d)[None].copy(); f[0,:2,:2] = [[0,-1],[1,0]]
            tau, volume = stress(f, np.array([False]))
            np.testing.assert_allclose(tau, 0, atol=1e-10)
            np.testing.assert_allclose(volume, 1)

    def test_liquid_has_no_static_shear_and_resists_compression(self):
        f = np.array([[[1,.2],[0,1]], [[.9,0],[0,.9]]])
        tau, _ = stress(f, np.array([True,True]))
        np.testing.assert_allclose(tau[0], 0, atol=1e-10)
        self.assertLess(tau[1,0,0], 0)
        self.assertAlmostEqual(tau[1,0,0], tau[1,1,1])
        self.assertEqual(tau[1,0,1],0)

    def test_contact_exchanges_momentum_and_dissipates_energy(self):
        x=np.array([[.06,0],[0,.07],[-.07,0]])
        v=np.array([[-1.,0],[0,-.5],[.2,0]]);m=np.array([1.,2.,.5])
        body=np.array([.1,.2]);mass=3.
        before=(m[:,None]*v).sum(axis=0)+mass*body
        energy=.5*np.sum(m[:,None]*v*v)+.5*mass*(body@body)
        impulse,count=contact(x,v,m,np.zeros(2),body,.1,mass)
        np.testing.assert_allclose((m[:,None]*v).sum(axis=0)+mass*body,before,atol=1e-12)
        self.assertLessEqual(.5*np.sum(m[:,None]*v*v)+.5*mass*(body@body),energy+1e-12)
        self.assertGreater(impulse,0);self.assertGreater(count,0)

    def test_freefall_transfer_in_2d_and_3d(self):
        for d in (2,3):
            model=CoupledDemo(settings({'dimensions':d}))
            start=model.x.copy();dt=.0002
            for _ in range(10):model.step(dt)
            np.testing.assert_allclose(model.v,np.broadcast_to(model.gravity*10*dt,model.v.shape),atol=1e-10)
            np.testing.assert_allclose(model.x,start+model.gravity*dt*dt*55,atol=1e-10)
            self.assertLess(model.max_mass_error,1e-12)

    def test_checkpoint_frames_and_wall_budget(self):
        result=CoupledDemo(settings({'duration_s':.02,'frames':3})).run()
        self.assertEqual([f['time_s'] for f in result['frames']],[0,.01,.02])
        self.assertTrue(np.isfinite(result['frames'][-1]['positions']).all())
        with self.assertRaises(TimeoutError):CoupledDemo(settings({})).run(wall_seconds=0)

    def test_cancellation_checked_during_integration(self):
        calls=[]
        def check():
            calls.append(1)
            if len(calls)>4:raise ProfileLocked('Ended test session')
        with self.assertRaises(ProfileLocked):CoupledDemo(settings({})).run(check)
        self.assertEqual(len(calls),5)


class PhysicsPublishing(unittest.TestCase):
    def fixture(self, root):
        (root/'Agent').mkdir()
        (root/'Agent/hardware_profiles.json').write_text((ROOT/'Agent/hardware_profiles.json').read_text())

    def test_atomic_export_viewer_and_distinct_runs(self):
        with tempfile.TemporaryDirectory(dir=FIXTURES) as tmp:
            root=Path(tmp);self.fixture(root)
            result=run({'duration_s':.02,'frames':3},root)
            files=[Path(p) for p in result['files']]
            self.assertTrue(all(p.is_file() and p.is_relative_to(root/'Outputs') for p in files))
            data=json.loads(next(p for p in files if p.suffix=='.json').read_text())
            self.assertEqual(data['config']['dimensions'],2)
            html=Path(result['viewer']).read_text()
            self.assertIn('type="range"',html);self.assertNotIn('https://',html)
            self.assertLess(result['output_bytes'],16*1024**2)
            again=run({'duration_s':.02,'frames':3},root)
            self.assertNotEqual(again['viewer'],result['viewer'])
            self.assertFalse(list(root.rglob('*.partial')))

    def test_low_memory_rejects_before_simulation(self):
        with tempfile.TemporaryDirectory(dir=FIXTURES) as tmp:
            root=Path(tmp);self.fixture(root)
            with patch('runtime_policy.memory_info',return_value=(8*1024**3,1024**3)), patch.object(CoupledDemo,'run') as simulate:
                with self.assertRaisesRegex(RuntimeError,'RAM'):run({},root)
            simulate.assert_not_called()

    def test_closed_installation_fails_before_outputs(self):
        with tempfile.TemporaryDirectory(dir=FIXTURES) as tmp:
            root=Path(tmp);(root/'Private/Users').mkdir(parents=True)
            with patch.dict('os.environ',{},clear=True), self.assertRaises(ProfileLocked):run({},root)
            self.assertFalse((root/'Outputs').exists())

    def test_changed_profile_at_publish_removes_only_new_result(self):
        with tempfile.TemporaryDirectory(dir=FIXTURES) as tmp:
            root=Path(tmp);self.fixture(root)
            original=Path.rename
            ended=[False]
            def rename(path,target):
                result=original(path,target);ended[0]=True;return result
            def capture(_root):
                if ended[0]:raise ProfileLocked('Test logout during publication')
                return None
            with patch('profile_paths.capture',side_effect=capture),patch.object(Path,'rename',rename):
                with self.assertRaises(ProfileLocked):run({'duration_s':.02,'frames':3},root)
            self.assertFalse(list((root/'Outputs').rglob('*.*')))

    def test_viewer_cannot_break_out_of_embedded_data(self):
        html=document({'title':'</script><script>alert(1)</script>'})
        self.assertNotIn('</script><script>alert',html)
        self.assertIn('\\u003c/script>',html)


if __name__=='__main__':unittest.main()
