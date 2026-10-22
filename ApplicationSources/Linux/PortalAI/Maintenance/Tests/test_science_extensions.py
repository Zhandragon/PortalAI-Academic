import io,json,math,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from Scientific.biology_tool import Context,run,publish
from Scientific import sequence_screening as seq
from Scientific import molecular_screening as mol
from Scientific import engineering_extensions as eng
from Scientific import circuit_extensions as circuit
from Scientific import paper_context,world_scene

class ScienceExtensionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.context=Context(self.root)
    def tearDown(self):self.tmp.cleanup()
    def test_alerts_and_synthesis(self):
        result,_=mol.screen({'smiles':['CCO','Oc1ccc(O)cc1']},self.context)
        self.assertEqual(len(result['molecules']),2)
        self.assertTrue(all(1<=r['synthetic_accessibility_1_easy_10_hard']<=10 for r in result['molecules']))
        self.assertTrue(result['molecules'][1]['structural_alerts'])
        self.assertTrue(result['molecules'][0]['no_alerts_is_not_safety'])
    def test_invalid_smiles(self):
        with self.assertRaises(ValueError):mol.screen({'smiles':'not a molecule'},self.context)
    def test_affinity_fit_known_Kd(self):
        x=[0,1,2,5,10,20,50];y=[3+7*v/(5+v) for v in x]
        result,_=mol.affinity({'concentrations':x,'response':y,'concentration_unit':'nM'},self.context)
        self.assertAlmostEqual(result['Kd'],5,places=5)
        self.assertLess(result['residual_RMSE'],1e-6)
    def test_unidentifiable_affinity(self):
        with self.assertRaises(ValueError):mol.affinity({'concentrations':[0,1,2,3,4],'response':[1]*5,'concentration_unit':'nM'},self.context)
    def test_seed_matches_bruteforce(self):
        import random
        rng=random.Random(41)
        for count in range(4):
            q=''.join(rng.choices('ACGT',k=20));ref=''.join(rng.choices('ACGT',k=100))+q[:4]+'A'+q[5:]+q
            actual=list(seq.hits(ref,q,count,lambda:None));expected=[]
            for at in range(len(ref)-len(q)+1):
                diff=[j+1 for j,(a,b) in enumerate(zip(q,ref[at:])) if a!=b]
                if len(diff)<=count:expected.append((at,diff))
            self.assertEqual(actual,expected)
    def test_specificity_both_strands_pam(self):
        q='ACGTTGCAATGCCGTAACGT';text='AAAA'+q+'AGG'+'TTTT'+seq.rc(q+'TGG')+'AAAA'
        p=self.root/'genome.fa';p.write_text('>chr1\n'+text+'\n')
        result,_=seq.specificity({'reference':str(p),'queries':[{'name':'q','sequence':q,'pam':'NGG'}],'mismatches':0},self.context)
        self.assertEqual({r['strand'] for r in result['hits']},{'+','-'})
        self.assertEqual(result['reference_bases'],len(text));self.assertTrue(result['coverage_complete'])
    def test_fasta_block_boundaries(self):
        q='ACGTTGCAATGCCGTAACGT';p=self.root/'ref.fa';p.write_text('>a\n'+'T'*27+seq.rc(q+'AGG')+'T'*100+'\n')
        original=seq.fasta_blocks
        with patch.object(seq,'fasta_blocks',side_effect=lambda path,overlap,check:original(path,overlap,check,block=32)):
            r,_=seq.specificity({'reference':str(p),'queries':[{'name':'q','sequence':q,'pam':'NGG'}],'mismatches':0},self.context)
        self.assertEqual(len(r['hits']),1);self.assertEqual(r['hits'][0]['start'],30)
    def test_ambiguity_reported(self):
        q='ACGTTGCAATGCCGTAACGT';p=self.root/'ref.fa';p.write_text('>a\n'+q+'NNN\n')
        r,_=seq.specificity({'reference':str(p),'queries':[{'name':'q','sequence':q}]},self.context)
        self.assertEqual(r['ambiguous_reference_bases'],3)
    def test_duplicate_contig_rejected(self):
        p=self.root/'ref.fa';p.write_text('>a\nACGT\n>a\nACGT\n')
        with self.assertRaises(ValueError):list(seq.fasta_blocks(p,20,self.context.check))
    def test_circular_annotation(self):
        result,contents=seq.annotate({'sequence':'ACGTCCCCGGGTTTAA','circular':True,'features':[{'name':'junction','sequence':'TTTAAACGT','role':'reference','source':'synthetic fixture'}]},self.context)
        self.assertEqual(result['features'][0]['end_unwrapped'],20)
        from Bio import SeqIO
        record=SeqIO.read(io.StringIO(contents['annotated.gb']),'genbank')
        self.assertEqual(str(record.features[0].extract(record.seq)),'TTTAAACGT')
    def test_paper_query_provenance(self):
        text='Methods: controlled cells were measured. '*50+'Results: binding response at 5 nM was measured. '*50
        result,contents=paper_context.run({'text':text,'query':'binding response','max_characters':2000},self.context)
        self.assertLessEqual(result['selected_characters'],2000);self.assertGreater(result['omitted_chunks'],0)
        self.assertTrue(result['source_url_unverified']);self.assertIn('all_chunks',json.loads(contents['evidence.json']))
    def test_paper_xml_entities_rejected(self):
        with self.assertRaises(ValueError):paper_context.run({'text':'<!DOCTYPE a [<!ENTITY b "bad">]><a>&b;</a>'},self.context)
    def test_beam_failure_ranking(self):
        m={'length_m':1,'area_m2':.001,'I_m4':1e-8,'c_m':.01,'E_Pa':200e9,'yield_Pa':250e6,'axial_force_N':-100000,'moment_Nm':100}
        result,_=eng.integrity({'members':[m],'safety_factor':2},self.context)
        r=result['members_ranked_by_utilization'][0]
        self.assertAlmostEqual(r['Euler_critical_compression_N'],math.pi**2*2000)
        self.assertIn('buckling_utilization',r['screen_flags'])
    def test_drag_reduces_range(self):
        p={'position_m':[0,0,1],'velocity_m_s':[20,0,20],'mass_kg':1,'area_m2':.1,'drag_coefficient':0}
        ideal,_=eng.projectile(p,self.context);drag,_=eng.projectile(dict(p,drag_coefficient=.47),self.context)
        self.assertTrue(drag['ground_impact']);self.assertLess(drag['last_position_m'][0],ideal['last_position_m'][0]);self.assertAlmostEqual(drag['last_position_m'][2],0,places=6)
    def test_structured_transistor(self):
        text,nodes=circuit.netlist({'components':[{'ref':'V1','nodes':['vcc','0'],'value':5},{'ref':'R1','nodes':['vcc','out'],'value':1000},{'ref':'Q1','nodes':['out','base','0'],'model':'switch'}],'models':[{'name':'switch','type':'NPN','parameters':{'BF':100}}]})
        self.assertIn('Q1 out base 0 switch',text);self.assertIn('.model switch NPN',text)
    def test_no_spice_command_injection(self):
        with self.assertRaises(ValueError):circuit.netlist({'components':[{'ref':'V1\n.control','nodes':['v','0'],'value':1}]})
    def test_unknown_model_parameter(self):
        with self.assertRaises(ValueError):circuit.netlist({'components':[{'ref':'V1','nodes':['v','0'],'value':1}],'models':[{'name':'D1','type':'D','parameters':{'execute':'evil'}}]})
    def test_mesh_project(self):
        import trimesh
        p=self.root/'box.stl';p.write_bytes(trimesh.creation.box([10,10,10]).export(file_type='stl'))
        result,files=eng.print_prepare({'file':str(p)},self.context)
        self.assertTrue(result['watertight'])
        with zipfile.ZipFile(io.BytesIO(files['supported-project.3mf'])) as z:self.assertIn(b'support_material = 1',z.read('Metadata/Slic3r_PE.config'))
    def test_open_mesh_rejected(self):
        import trimesh
        m=trimesh.creation.box();m.update_faces(list(range(10)));p=self.root/'open.stl';p.write_bytes(m.export(file_type='stl'))
        with self.assertRaises(ValueError):eng.print_prepare({'file':str(p)},self.context)
    def test_world_schema(self):
        self.assertEqual(world_scene.validate({'objects':[{'shape':'box'}]})['objects'][0]['mass'],1)
        with self.assertRaises(ValueError):world_scene.validate({'objects':[{'shape':'sphere','size':[1,2,1]}]})
        with self.assertRaises(ValueError):world_scene.validate({'objects':[{'position':[0,float('nan'),0]}]})
    def test_binary_publication(self):
        import shutil
        import runtime_policy
        (self.root/'Agent').mkdir();shutil.copyfile(runtime_policy.ROOT/'Agent/hardware_profiles.json',self.root/'Agent/hardware_profiles.json')
        files=publish(self.context,{}, {'mesh.bin':b'\x00\xff\x80'})
        self.assertEqual(Path(files[0]).read_bytes(),b'\x00\xff\x80')
    def test_stop_prevents_publication(self):
        import time
        p=self.root/'Agent/.runtime/qwen_last_stop.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'stopped_at':time.time()+1}))
        with self.assertRaises(RuntimeError):publish(self.context,{}, {'never.txt':'no'})
        self.assertFalse((self.root/'Outputs').exists())
    def test_catalog_both_routes(self):
        from Scientific.science_extensions import HELP
        from Scientific.biology_tool import HELP as both
        self.assertTrue(set(HELP)<=set(both))
    def test_excel_values_and_sheet(self):
        import openpyxl
        from Scientific.table_workbook import frame
        p=self.root/'book.xlsx';book=openpyxl.Workbook();book.active.append(['name','value']);book.active.append(['a',2]);book.save(p)
        df=frame({'path':str(p)},self.root);self.assertEqual(df.iloc[0]['value'],2)
    def test_excel_uncached_formula(self):
        import openpyxl
        from Scientific.table_workbook import frame
        p=self.root/'book.xlsx';book=openpyxl.Workbook();book.active.append(['value']);book.active.append(['=1+1']);book.save(p)
        with self.assertRaises(ValueError):frame({'path':str(p)},self.root)
        with self.assertRaises(ValueError):frame({'path':str(p),'use_cached_formulas':True},self.root)
    def test_nan_bounds(self):
        from Scientific.extensions_common import number
        for v in (float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):number(v,'test')

if __name__=='__main__':unittest.main()
