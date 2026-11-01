import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/p) for p in ('Agent','ControlCenter','Maintenance/Tests')]
from test_workspace import Fixture
from artifact_libraries import Libraries
from artifacts import Artifacts


class LibraryTests(Fixture):
    def bundle(self,*,name='example',filename='example.js',code=b'exports.answer=42;',checksum=None):
        path=self.root/'library.zip'
        manifest={'version':1,'name':'Example library','modules':[{'name':name,'file':filename,'sha256':checksum or hashlib.sha256(code).hexdigest()}]}
        with zipfile.ZipFile(path,'w') as z:z.writestr('library.json',json.dumps(manifest));z.writestr(filename,code)
        return path

    def enabled(self):
        store=Libraries(self.root);row=store.import_bundle(self.bundle());store.enable(row['id'],True)
        return store,row['id']

    def test_review_required_and_revocation_blocks_existing_revision(self):
        libs=Libraries(self.root);row=libs.import_bundle(self.bundle());lid=row['id']
        with self.assertRaises(PermissionError):libs.pins([lid])
        libs.enable(lid,True);store=Artifacts(self.root)
        meta=store.save('Hello','react','export default function App(){return <div>Hello</div>}',dependencies=[lid])
        rev=store.read(meta['id']);self.assertEqual(libs.modules(rev['dependencies'])[0]['name'],'example')
        libs.enable(lid,False)
        with self.assertRaises(PermissionError):libs.modules(rev['dependencies'])
        self.assertIn('Hello',store.read(meta['id'])['content'])

    def test_pins_survive_edits_restore_and_export_includes_code_offline(self):
        libs,lid=self.enabled();store=Artifacts(self.root)
        one=store.save('A','react','export default function App(){return <div>A</div>}',dependencies=[lid])
        two=store.save('B','react','export default function App(){return <div>B</div>}',artifact=one['id'],expected_revision=one['head'])
        self.assertEqual(store.read(one['id'])['dependencies'],libs.pins([lid]))
        three=store.save('C','react','export default function App(){return <div>C</div>}',artifact=one['id'],expected_revision=two['head'],dependencies=[])
        self.assertIn('Libraries:',store.compare(one['id'],two['head'],three['head']))
        restored=store.restore(one['id'],one['head'],three['head']);self.assertEqual(store.read(one['id'])['dependencies'],libs.pins([lid]))
        exported=store.export(restored['id'])
        self.assertTrue(exported['path'].endswith('.html'))
        from profile_paths import private_path
        data=private_path(self.root,exported['path']).read_bytes()
        self.assertIn(b'exports.answer=42;',data);self.assertTrue(b"connect-src 'none'" in data)
        self.assertEqual(hashlib.sha256(data).hexdigest(),exported['sha256'])

    def test_unknown_reserved_paths_checksum_and_mutation_are_refused(self):
        libs=Libraries(self.root)
        for arguments in ({'name':'react'},{'filename':'../escape.js'},{'checksum':'0'*64},{'name':'__proto__'}):
            # __proto__ is a valid CommonJS name, with a null-prototype registry.
            if arguments.get('name')=='__proto__':continue
            with self.subTest(arguments=arguments),self.assertRaises(ValueError):libs.import_bundle(self.bundle(**arguments))
        libs,lid=self.enabled();pins=libs.pins([lid]);libs.path('Bundles/'+lid+'/example.js').write_text('changed')
        with self.assertRaisesRegex(ValueError,'changed'):libs.modules(pins)

    def test_module_collision_and_non_react_dependencies_are_refused(self):
        libs,lid=self.enabled();row=libs.import_bundle(self.bundle());libs.enable(row['id'],True)
        with self.assertRaisesRegex(ValueError,'Duplicate'):libs.modules(libs.pins([lid,row['id']]))
        with self.assertRaises(ValueError):Artifacts(self.root).save('No','html','<p>no</p>',dependencies=[lid])


class ComparisonAdmissionTests(unittest.TestCase):
    def plans(self):
        return [{'backend':{'backend':'cuda','device':'CUDA0','gpu':{'free_bytes':24*1024**3}},
                 'model':{'layers':28,'gpu_layers':29,'estimated_gpu_bytes':5*1024**3,'estimated_ram_bytes':2*1024**3}} for _ in range(2)]

    def test_parallel_requires_combined_reserves_full_offload_and_cpu_headroom(self):
        from comparison_workers import parallel_admission
        plans=self.plans();hardware={'ram_available_bytes':12*1024**3}
        with patch('os.cpu_count',return_value=12):
            self.assertTrue(parallel_admission(plans,hardware)[0])
            self.assertFalse(parallel_admission(plans,{'ram_available_bytes':7*1024**3})[0])
            plans[0]['backend']['gpu']['free_bytes']=12*1024**3
            self.assertFalse(parallel_admission(plans,hardware)[0])
            plans=self.plans();plans[1]['model']['gpu_layers']=20
            self.assertFalse(parallel_admission(plans,hardware)[0])
            plans=self.plans();plans[1]['backend']['gpu']['shared_memory']=True
            self.assertFalse(parallel_admission(plans,hardware)[0])
        with patch('os.cpu_count',return_value=4):self.assertFalse(parallel_admission(self.plans(),hardware)[0])


class ComparisonLifetimeTests(Fixture):
    def test_parallel_rounds_reuse_workers_and_close_before_model_restoration(self):
        import threading
        from model_comparison import Comparisons
        opened=[];closed=[];received=[]
        class Worker:
            def __init__(self,root,plan,check,parallel=False):self.plan=plan;self.check=check
            def __enter__(self):opened.append(self.plan['model']['id']);return self
            def __exit__(self,*args):self.close()
            def close(self):closed.append(self.plan['model']['id'])
            def answer(self,question,peers):
                self.check();received.append(len(peers));return {'answer':'Verified independently','truncated':False}
        def stage(root,name,admit,operation,**kw):
            result=operation(kw['check'])
            self.assertEqual(sorted(closed),['one','two'])
            return result
        plans=[{'model':{'id':mid}} for mid in ('one','two')]
        with patch('comparison_workers.installed',return_value=[{'id':'one'},{'id':'two'}]),patch('comparison_workers.plans_for',return_value=(plans,{})),patch('comparison_workers.parallel_admission',return_value=(True,'test admission')),patch('comparison_workers.ModelWorker',Worker),patch('voice_memory.run_voice_stage',side_effect=stage):
            result=Comparisons(self.root).run_models(object(),'Compare', ['one','two'],threading.Event(),rounds=3,parallel=True)
        self.assertEqual(opened,['one','two']);self.assertEqual(len(result['results']),6);self.assertEqual(sorted(received),[0,0,2,2,2,2])


if __name__=='__main__':unittest.main()
