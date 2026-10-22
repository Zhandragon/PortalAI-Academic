import io,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from Scientific import plannotate_tool as pt,sequence_screening as seq

class AnnotationTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  self.context=SimpleNamespace(root=self.root,check=lambda:None)
 def tearDown(self):self.temp.cleanup()
 def test_default_routes_to_plannotate(self):
  with patch.object(pt,'run',return_value=('yes',{})) as run:
   self.assertEqual(seq.annotate({'sequence':'ACGT'*10},self.context),('yes',{}));run.assert_called_once()
 def test_exact_legacy_preserved(self):
  r,_=seq.annotate({'sequence':'ACGT'*10,'features':[{'name':'x','sequence':'ACGTACGT','role':'reference','source':'test'}]},self.context)
  self.assertGreater(len(r['features']),0);self.assertEqual(r['features'][0]['identity'],1)
 def test_reject_unsupported_arguments(self):
  with self.assertRaises(ValueError):pt.run({'sequence':'ACGT'*10,'shell':'bad'},self.context)
 def test_reject_oversize_sequence(self):
  with self.assertRaises(ValueError):pt.run({'sequence':'A'*100001},self.context)
 def test_reject_sequence_and_file(self):
  with self.assertRaises(ValueError):pt.run({'sequence':'ACGT'*10,'file':'x'},self.context)
 def test_reject_bad_mode(self):
  with self.assertRaises(ValueError):pt.run({'sequence':'ACGT'*10,'mode':'full_rna'},self.context)
 def test_reject_bad_topology(self):
  with self.assertRaises(ValueError):pt.run({'sequence':'ACGT'*10,'circular':'false'},self.context)
 def test_standard_metadata_and_worker_budget(self):
  pin={'version':'2','revision':'pinned','database_version':2}
  with patch.object(pt,'inventory',return_value=pin),patch.object(pt,'worker',return_value=({'features':[]},{})) as worker:
   r,_=pt.run({'sequence':'ACGT'*10},self.context)
  self.assertEqual(worker.call_args.kwargs['timeout'],100)
  self.assertTrue(worker.call_args.args[2]['circular']);self.assertEqual(worker.call_args.args[2]['mode'],'standard')
  self.assertFalse(r['uploaded_sequence']);self.assertIn('Rfam',r['limitations'][0])
 def test_file_topology(self):
  text='LOCUS       tiny                      40 bp    DNA     linear   UNK 01-JAN-2000\nDEFINITION  synthetic.\nACCESSION   tiny\nORIGIN\n        1 '+('acgt'*10)+'\n//\n'
  with patch.object(pt,'read',return_value=text.encode()),patch.object(pt,'inventory',return_value={'version':'2','revision':'p','database_version':2}),patch.object(pt,'worker',return_value=({},{})) as worker:
   pt.run({'file':'fixture.gb'},self.context)
   self.assertFalse(worker.call_args.args[2]['circular'])
 def test_missing_inventory_fails(self):
  with self.assertRaises(FileNotFoundError):pt.inventory(self.root)
 def test_inventory_traversal(self):
  p=self.root/'Maintenance/Imports/plannotate.json';p.parent.mkdir(parents=True)
  p.write_text(json.dumps({'files':[{'path':'Tools/pLannotate/../../private','bytes':1,'sha256':'0'*64}]}))
  with self.assertRaises(ValueError):pt.inventory(self.root)
 def test_map_escapes_labels(self):
  r=pt.feature_svg(100,[{'qstart':90,'qend':110,'sframe':1,'name':'<script>&x'}])
  self.assertNotIn('<script>',r);self.assertIn('&lt;script&gt;',r);self.assertEqual(r.count('<rect'),3)
 def test_checks_have_honest_rna_warning(self):
  import science_extension_checks
  rows=science_extension_checks.rows(self.root)
  self.assertTrue(any(r['status']=='WARN' and 'RNA' in r['label'] for r in rows))
  self.assertFalse(any(r['status']=='PASS' for r in rows))

if __name__=='__main__':unittest.main()
