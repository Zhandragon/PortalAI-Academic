import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from Scientific import world_scene, science_extensions

class PhysicsWorldTests(unittest.TestCase):
    def test_examples_and_defaults(self):
        for example in world_scene.describe()['examples'].values():
            normalized=world_scene.validate(example)
            self.assertEqual(normalized,world_scene.validate(normalized))
        self.assertEqual(world_scene.validate({'objects':[{}]})['objects'][0]['id'],'body0')

    def test_bounds_and_types(self):
        for p in ({'objects':None},{'objects':[{'mass':True}]},{'wind':[0,float('inf'),0]},
                  {'objects':[{'id':'bad\n'}]},{'objects':[{'code':'alert(1)'}]},
                  {'objects':[{}, {'id':'body0'}]}, {'fluids':[{'counts':[6,6,6]},{'counts':[6,6,6]}]}):
            with self.subTest(p=p),self.assertRaises(ValueError):world_scene.validate(p)

    def test_stiff_spring_rejected(self):
        with self.assertRaisesRegex(ValueError,'stiff'):
            world_scene.validate({'objects':[{'id':'a','mass':0},{'id':'b','mass':.001}],
                                  'connections':[{'a':'a','b':'b','stiffness':100000}]})

    def test_bad_connections(self):
        for c in ({'a':'a','b':'a'},{'a':'a','b':'absent'},{'a':'a','b':'b','kind':'rope','length':1}):
            with self.subTest(c=c),self.assertRaises(ValueError):
                world_scene.validate({'objects':[{'id':'a','position':[0,5,0]},{'id':'b','position':[3,5,0]}],'connections':[c]})

    def test_fragment_capacity_reserved(self):
        with self.assertRaisesRegex(ValueError,'96'):
            world_scene.validate({'objects':[{'break_speed':1} for _ in range(13)]})
        with self.assertRaisesRegex(ValueError,'Breakage'):
            world_scene.validate({'objects':[{'shape':'sphere','break_speed':1}]})

    def test_liquid_guards(self):
        for p in ({'liquids':[{},{}]},{'liquids':[{}],'gravity':[1,-9.81,0]},
                  {'liquids':[{'position':[0,4,0]}],'fluids':[{}]},
                  {'fluids':[{}, {'density':500}]}):
            with self.subTest(p=p),self.assertRaises(ValueError):world_scene.validate(p)

    def test_no_input_mutation(self):
        p={'objects':[{}]};before=copy.deepcopy(p);world_scene.validate(p);self.assertEqual(p,before)

    def test_schema_route_in_shared_catalog(self):
        from Scientific.biology_tool import HELP
        self.assertIn('physics.world_schema',HELP)
        r,files=science_extensions.run('physics.world_schema',{},None)
        self.assertEqual(r['limits']['fluid_particles'],256);self.assertFalse(files)
        with self.assertRaises(ValueError):science_extensions.run('physics.world_schema',{'code':'oops'},None)

    def test_document_escaping_and_single_template_expansion(self):
        source=Path(world_scene.__file__).parent
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)/'Scientific';base.mkdir()
            for name in ('world_scene.html','world_physics.js','world_ui.js'):
                (base/name).write_bytes((source/name).read_bytes())
            library=Path(tmp)/'stub.js';library.write_text('/* verified library substitute for injection test */')
            context=SimpleNamespace(root=Path(tmp))
            with patch.object(world_scene,'asset',return_value=library):
                result,files=world_scene.run({'title':'</script><script>alert(1)</script> __UI__','export':True,'output_dir':'ignored here'},context)
            html=files['world.html']
            self.assertNotIn('</script><script>alert(1)</script>',html)
            self.assertIn('__UI__',html)  # data remains data; no second expansion
            self.assertIn("connect-src 'none'",html)
            self.assertEqual(result['fixed_step_seconds'],1/120)

    def test_help_and_readiness_cover_new_files(self):
        import help_catalog,science_extension_checks
        self.assertIn('physics_lab',help_catalog.filtered_topic_keys('particles'))
        paths=next(v for k,v in science_extension_checks.GROUPS.items() if k.startswith('Physics Lab'))
        for name in ('world_physics.js','world_ui.js','world_schema.json','world_examples.json'):
            self.assertIn('Scientific/'+name,paths)

if __name__=='__main__':unittest.main()
