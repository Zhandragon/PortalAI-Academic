"""Scientific invariants and profile/Stop boundaries; synthetic data only."""
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
if ROOT.name=='portable':ROOT=Path('/portable')
sys.path[:0]=[str(ROOT),str(ROOT/'Agent'),str(ROOT/'Tools'),str(ROOT/('Runtime/ScientificPython/packages' if os.name=='nt' else 'Runtime/LinuxPackages/science'))]
from Scientific import biology as b
from Scientific import biology_tool as bt
from Scientific.protein_design import backbone
from Bio import SeqIO


class Calculations(unittest.TestCase):
    def test_rfc10_scar_and_annotation(self):
        result,files=b.assemble({'method':'biobrick_rfc10','parts':[{'name':'left','sequence':'AAAACC'},{'name':'right','sequence':'GGTATA','strand':-1}]})
        self.assertEqual(result['sequence'],'AAAACCTACTAGAGTATACC')
        record=SeqIO.read(io.StringIO(files['assembly.gb']),'genbank')
        self.assertEqual(str(record.features[1].extract(record.seq)),'GGTATA')
        self.assertEqual(record.annotations['topology'],'linear')
    def test_rfc10_rejects_sites_and_fusion_assumption(self):
        for motif in ('GAATTC','TCTAGA','ACTAGT','CTGCAG'):
            with self.assertRaises(ValueError):b.assemble({'method':'biobrick_rfc10','parts':[{'name':'a','sequence':motif}]})
        with self.assertRaises(ValueError):b.assemble({'circular':True,'parts':[{'name':'a','sequence':'ACGT'}]})
    def test_overlap_and_circle_coordinates(self):
        shared='AACCGGTTAACC';other='TTGGCCAATTGG'
        parts=[{'name':'vector','role':'backbone','sequence':shared+'GGAA'+other},
               {'name':'insert','sequence':other+'CCTT'+shared,'strand':1}]
        result,files=b.assemble({'method':'overlap','parts':parts,'overlaps':[12,12],'circular':True})
        self.assertEqual(result['sequence'],shared+'GGAA'+other+'CCTT')
        record=SeqIO.read(io.StringIO(files['assembly.gb']),'genbank')
        self.assertEqual(str(record.features[1].extract(record.seq)),parts[1]['sequence'])
        parts[1]['sequence']='G'+parts[1]['sequence'][1:]
        with self.assertRaises(ValueError):b.assemble({'method':'overlap','parts':parts,'overlaps':[12,12],'circular':True})
    def test_sites_across_circular_origin_and_both_strands(self):
        self.assertTrue(any(x['enzyme']=='EcoRI' and x['start']==4 for x in b.sites('ATTCGA',True)))
        self.assertTrue(any(x['enzyme']=='BsaI' and x['strand']==-1 for x in b.sites('GAGACC')))
    def test_inputs_are_not_silently_sanitized(self):
        for value in ('>sample\nACGT','ACGT?','ACGN','',True):
            with self.assertRaises(ValueError):b.sequence(value)
        for value in (True,1.5,float('nan'),float('inf')):
            with self.assertRaises(ValueError):b.integer(value,'n',1,3)
    def test_map_escapes_labels(self):
        _,files=b.assemble({'parts':[{'name':'<script>','sequence':'ACGT'}]})
        self.assertNotIn('<script>',files['assembly.svg'])
    def test_genbank_preserves_join_and_region(self):
        from Bio.Seq import Seq
        from Bio.SeqRecord import SeqRecord
        from Bio.SeqFeature import SeqFeature,FeatureLocation,CompoundLocation
        record=SeqRecord(Seq('ACGT'*20),id='test',annotations={'molecule_type':'DNA'})
        record.features=[SeqFeature(CompoundLocation([FeatureLocation(2,8),FeatureLocation(20,29)]),type='CDS')]
        stream=io.StringIO();SeqIO.write(record,stream,'genbank')
        result=b.genome_features({'text':stream.getvalue(),'start':4,'end':24})
        self.assertEqual(len(result['features'][0]['segments']),2)
        self.assertEqual(result['sequence'],'ACGT'*5)
    def test_variant_identity_and_wildtype(self):
        result=b.protein_variants({'sequence':'ACDEFGHIK','variants':[{'name':'test','substitutions':['A1G']}]})
        self.assertEqual(result['variants'][1]['sequence'],'GCDEFGHIK')
        for edits in (['C1G'],['A1G','A1V'],['A10G']):
            with self.assertRaises(ValueError):b.protein_variants({'sequence':'ACDEFGHIK','variants':[{'substitutions':edits}]})
    def test_parts_require_matched_measurements(self):
        common={'host':'host','condition':'condition','role':'RBS','metric':'output','unit':'AU'}
        rows=[{**common,'name':'a','source':'measured','value':2},{**common,'name':'b','source':'measured','value':5},{**common,'name':'c','source':'measured','value':4,'host':'different'}]
        result=b.rank_parts({**common,'parts':rows,'target':4})
        self.assertEqual([r['name'] for r in result['ranked']],['b','a'])
        self.assertEqual(result['excluded'],['c'])
    def test_circuit_analytic_decay_and_steady_state(self):
        result=b.circuit({'duration':10,'genes':[{'name':'reporter','transcription':0,'translation':0,'mrna_decay':1,'protein_decay':.5,'initial_protein':2}]})
        self.assertAlmostEqual(result['trajectories']['reporter']['protein'][-1],2*math.exp(-5),places=6)
        result=b.circuit({'duration':10,'genes':[{'name':'reporter','transcription':2,'translation':3,'mrna_decay':1,'protein_decay':.5,'initial_mrna':2,'initial_protein':12}]})
        self.assertAlmostEqual(result['trajectories']['reporter']['protein'][-1],12,places=8)
    def test_circuit_cancellation_and_no_eval(self):
        with self.assertRaises(ValueError):b.circuit({'duration':1,'genes':[{'name':'x','transcription':'__import__("os")','translation':1,'mrna_decay':1,'protein_decay':1}]})
        with self.assertRaisesRegex(RuntimeError,'cancelled'):
            b.circuit({'duration':1,'genes':[{'name':'x','transcription':1,'translation':1,'mrna_decay':1,'protein_decay':1}]},lambda:(_ for _ in ()).throw(RuntimeError('cancelled')))
    def test_bioprocess_batch_mass_balance(self):
        result=b.bioprocess({'mu_max':.2,'Ks':.5,'yield_xs':.4,'biomass_g_l':1,'substrate_g_l':10,'product_g_l':0,'volume_l':1,'duration_h':12})
        for x,s in zip(result['biomass_g_l'],result['substrate_g_l']):self.assertAlmostEqual(x+.4*s,5,places=6)
        self.assertEqual(result['volume_l'][-1],1)
    def test_bioprocess_feed_dilution(self):
        result=b.bioprocess({'mu_max':0,'Ks':.5,'yield_xs':.4,'biomass_g_l':1,'substrate_g_l':0,'product_g_l':2,'volume_l':1,'duration_h':2,'feed_l_h':.5})
        self.assertAlmostEqual(result['volume_l'][-1],2)
        self.assertAlmostEqual(result['biomass_g_l'][-1],.5,places=6)
        self.assertAlmostEqual(result['product_g_l'][-1],1,places=6)


class Boundaries(unittest.TestCase):
    def setUp(self):
        from validation_artifacts import ValidationArtifacts
        base=ROOT/'Maintenance/Validation/Biology_20261010'
        artifacts=ValidationArtifacts(ROOT,base.resolve())
        self.tmp=tempfile.TemporaryDirectory(dir=artifacts.path());self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);(self.root/'Agent').mkdir()
        (self.root/'Agent/hardware_profiles.json').write_text((ROOT/'Agent/hardware_profiles.json').read_text())
    def test_atomic_publication(self):
        result=bt.run('plasmid.assemble',{'parts':[{'name':'synthetic','sequence':'ACGT'}]},self.root)
        self.assertEqual(len(result['files']),4)
        self.assertTrue(all(Path(p).is_file() for p in result['files']))
        self.assertFalse(list(self.root.rglob('*.partial')))
    def test_logout_cleans_only_new_outputs(self):
        from profile_paths import ProfileLocked
        context=bt.Context(self.root);calls=0
        original=context.check
        def revoked():
            nonlocal calls
            calls+=1
            if calls==5:raise ProfileLocked('revoked')
            original()
        context.check=revoked
        with self.assertRaises(ProfileLocked):bt.publish(context,{}, {'a.json':'{}'})
        self.assertFalse(list(self.root.rglob('a.json')))
    def test_stop_blocks_late_publication(self):
        context=bt.Context(self.root)
        path=self.root/'Agent/.runtime';path.mkdir()
        (path/'qwen_last_stop.json').write_text(json.dumps({'stopped_at':time.time()+1}))
        with self.assertRaisesRegex(RuntimeError,'Stop'):bt.publish(context,{}, {'a.json':'{}'})
        self.assertFalse((self.root/'Outputs').exists())
    def test_output_escape_refused(self):
        with self.assertRaises(PermissionError):bt.publish(bt.Context(self.root),{'output_dir':str(self.root.parent)}, {'a.json':'{}'})
    def test_locked_profile_refused(self):
        (self.root/'Private/Users').mkdir(parents=True)
        with self.assertRaises(PermissionError):bt.run('protein.variants',{'sequence':'ACDEF'},self.root)
    def test_registry_checks_exact_identity(self):
        rows={'data':[{'name':'BBa_OTHER','uuid':'9b3b1fbd-1557-49a5-964a-7f8b491c9101'}]}
        with patch.object(bt,'public_request',return_value=(json.dumps(rows),'https://example.org',False)):
            with self.assertRaisesRegex(ValueError,'exact'):bt.network('igem.part',{'id':'BBa_J23100'},bt.Context(self.root))
    def test_fetch_does_not_accept_error_page(self):
        with patch.object(bt,'public_request',return_value=('ERROR: not found','https://example.org',False)):
            with self.assertRaises(ValueError):bt.network('ncbi.fetch',{'id':'BAD'},bt.Context(self.root))
    def test_native_and_cli_share_results(self):
        import science_tools
        from Scientific.science_core import run_operation
        p={'sequence':'ACDEFGHIK'}
        a=science_tools.dispatch(self.root,ROOT/'Runtime/SciencePackages',{'operation':'protein.variants','input':p})
        c=run_operation('protein.variants',p,self.root)
        self.assertEqual(a['data']['variants'],c['variants'])
    def test_browser_does_not_upload_sequence(self):
        result=bt.run('genome.browser',{'accession':'NC_000001.11','start':10,'end':50},self.root)
        self.assertIn('from=10',result['url']);self.assertFalse(result['uploaded_local_data'])
    def test_protein_device_is_not_silently_replaced(self):
        from Scientific.protein_design import design
        with self.assertRaisesRegex(ValueError,'CPU backend'):design({'device':'cuda'},bt.Context(self.root))
    def test_drive_launcher_relocation_and_ambiguity(self):
        import shutil,subprocess
        folder=self.root/'drive with spaces';folder.mkdir()
        if os.name=='nt':
            launcher=folder/'PortalAI.exe';shutil.copyfile(ROOT.parent/'PortalAI.exe',launcher)
            command=[str(launcher),'--check']
            for name in ('PortableAI','PortalAI'):
                child=folder/name;child.mkdir()
                shutil.copyfile(ROOT/'PortalAI.exe',child/'PortalAI.exe')
                (child/'Runtime/BootstrapPython').mkdir(parents=True);(child/'ControlCenter').mkdir()
                (child/'Runtime/BootstrapPython/pythonw.exe').touch()
                (child/'ControlCenter/control_center_bootstrap.py').touch()
                cp=subprocess.run(command,cwd=self.root,capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(cp.returncode,0 if name=='PortableAI' else 1)
        else:
            launcher=folder/'PortalAI.sh';shutil.copyfile(ROOT/'Launchers/DrivePortalAI.sh',launcher)
            for name in ('PortableAI','PortalAI'):
                child=folder/name;child.mkdir();(child/'PortalAI.sh').write_text('printf "LAUNCHED\\n"\n')
                cp=subprocess.run(['sh',str(launcher)],cwd=self.root,capture_output=True,text=True,timeout=10)
                self.assertEqual(cp.returncode,0 if name=='PortableAI' else 1)
                if name=='PortableAI':self.assertIn('LAUNCHED',cp.stdout)


if __name__=='__main__':unittest.main()
