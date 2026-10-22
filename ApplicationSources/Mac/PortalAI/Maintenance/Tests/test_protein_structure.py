"""Synthetic PDB/mmCIF, explicit sequence edits, and admission regressions."""
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'Agent'),str(ROOT/'Runtime/ScientificPython/packages')]
from Scientific import biology_tool as bt
from Scientific import protein_structure as ps
from Scientific.protein_design import validate_request, design, backbone


def pdb_text(count=8, declared=10, chain='A', start=2):
    lines=[]
    if declared:
        for offset in range(0,declared,13):
            lines.append(f'SEQRES {offset//13+1:3d} {chain} {declared:4d}  '+ ' '.join(['ALA']*min(13,declared-offset)))
    serial=0
    for n in range(start,start+count):
        for atom,element,dy in [('N','N',0),('CA','C',1),('C','C',2),('O','O',3)]:
            serial+=1
            lines.append(f'ATOM  {serial:5d} {atom:^4s} ALA {chain}{n:4d}    {float(n):8.3f}{float(dy):8.3f}{0.:8.3f}{1.:6.2f}{20.:6.2f}          {element:>2s}  ')
    return '\n'.join(lines)+'\nTER\nEND\n'


class ProteinStructureTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.path=self.root/'synthetic.pdb';self.path.write_text(pdb_text(),encoding='ascii')
        self.context=bt.Context(self.root)
    def inspect(self,**kw): return ps.inspect({'file':str(self.path),**kw},self.context)
    def variant(self,**kw):
        args={'file':str(self.path),'chain':'A','variants':[{'name':'test','substitutions':['A1G']}]}
        args.update(kw)
        return ps.run('protein.structure_variants',args,self.context)
    def test_observed_and_declared_are_distinct(self):
        r=self.inspect()['chain_details'][0]
        self.assertEqual(r['observed_sequence'],'A'*8)
        self.assertEqual(r['declared_sequence'],'A'*10)
        self.assertEqual(r['residue_map'][0]['number'],2)
    def test_large_chain_analysis_and_edits_are_not_mpnn(self):
        self.path.write_text(pdb_text(count=300,declared=302))
        r,files=self.variant()
        self.assertEqual(r['sequence_length'],302)
        self.assertFalse(r['structure_rebuilt']);self.assertFalse(r['function_validated'])
        self.assertIn('candidate-sequences.fasta',files)
        with self.assertRaisesRegex(ValueError,'selected chain has 300'):
            backbone(self.path.read_text(),'A')
    def test_sequence_edits_do_not_use_author_numbers(self):
        r,files=self.variant()
        report=json.loads(files['candidate-report.json'])
        self.assertEqual(report['variants'][1]['sequence'],'G'+'A'*9)
        self.assertIn('NOT PDB',r['numbering'])
        self.assertEqual(json.loads(files['structure.json'])['chain_details'][0]['residue_map'][0]['number'],2)
    def test_missing_declared_does_not_fall_back(self):
        self.path.write_text(pdb_text(declared=0))
        with self.assertRaisesRegex(ValueError,'absent'): self.variant()
        r,_=self.variant(sequence_source='observed')
        self.assertEqual(r['sequence_length'],8)
    def test_invalid_mutations_rejected(self):
        for edits in (['G1A'],['A11G'],['A1G','A1V'],['A0G']):
            with self.subTest(edits=edits),self.assertRaises(ValueError):
                self.variant(variants=[{'name':'x','substitutions':edits}])
    def test_functional_goal_is_not_silently_ignored(self):
        with self.assertRaisesRegex(ValueError,'Unsupported'): self.variant(target_pam='NGN')
    def test_invalid_or_ambiguous_chain_rejected(self):
        with self.assertRaises(ValueError): self.inspect(chain='missing')
        with self.assertRaisesRegex(ValueError,'explicit'): self.variant(chain=None)
    def test_candidate_name_cannot_inject_fasta(self):
        for name in ('x\n>fake','reference','../escape'):
            with self.assertRaises(ValueError): self.variant(variants=[{'name':name,'substitutions':['A1G']}])
    def test_incomplete_declared_sequence_rejected(self):
        self.path.write_text(pdb_text().replace('  10  ALA','  11  ALA'))
        with self.assertRaisesRegex(ValueError,'Incomplete'): self.inspect()
    def test_mmcif_author_chain_mapping(self):
        from Bio.PDB import PDBParser, MMCIFIO
        model=PDBParser(QUIET=True).get_structure('synthetic',io.StringIO(pdb_text(chain='Z')))
        out=io.StringIO();writer=MMCIFIO();writer.set_structure(model);writer.save(out)
        text=out.getvalue()+'\nloop_\n_entity_poly_seq.entity_id\n_entity_poly_seq.num\n_entity_poly_seq.mon_id\n'
        text+='\n'.join(f'1 {i} ALA' for i in range(1,11))+'\n#\nloop_\n_struct_asym.id\n_struct_asym.entity_id\nA 1\n#\n'
        self.path=self.root/'synthetic.cif';self.path.write_text(text)
        r=self.inspect(chain='Z')
        self.assertEqual(r['format'],'mmCIF')
        self.assertEqual(r['chain_details'][0]['declared_sequence'],'A'*10)
        self.assertEqual(r['chains'],{'Z':8})
    def test_legacy_inspection_path(self):
        r,files=ps.run('protein.inspect',{'input':str(self.path)},self.context)
        self.assertEqual(r['residues'],8)
        self.assertIn('structure-sequences.fasta',files)
    def test_conflicting_file_keys_fail(self):
        with self.assertRaises(ValueError): ps.inspect({'file':str(self.path),'input':str(self.path)},self.context)
    def test_size_cap(self):
        with patch.object(ps,'MAX_BYTES',10),self.assertRaisesRegex(ValueError,'20 MiB'): self.inspect()
    def test_atom_cap(self):
        with patch.object(ps,'MAX_ATOMS',1),self.assertRaisesRegex(ValueError,'atom'): self.inspect()
    def test_stop_before_read(self):
        state=self.root/'Agent/.runtime';state.mkdir(parents=True)
        (state/'qwen_last_stop.json').write_text(json.dumps({'stopped_at':time.time()+1}))
        with self.assertRaisesRegex(RuntimeError,'Stop'): self.inspect()
    def test_publication_and_input_preservation(self):
        before=self.path.read_bytes()
        with patch('runtime_policy.require_space'),patch('runtime_policy.memory_info',return_value=(16*1024**3,8*1024**3)):
            r=bt.run('protein.structure_variants',{'file':str(self.path),'chain':'A','variants':[{'name':'synthetic','substitutions':['A1G']}]},self.root)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(len(r['files']),4)
        self.assertTrue(all(Path(p).is_file() and Path(p).is_relative_to(self.root) for p in r['files']))
    def test_locked_account_rejects_structure(self):
        (self.root/'Private/Users').mkdir(parents=True)
        with self.assertRaises(PermissionError): bt.run('protein.inspect',{'file':str(self.path)},self.root)
    def test_output_escape_rejected(self):
        with patch('runtime_policy.require_space'),patch('runtime_policy.memory_info',return_value=(16*1024**3,8*1024**3)):
            with self.assertRaises(PermissionError): bt.run('protein.inspect',{'file':str(self.path),'output_dir':str(self.root.parent)},self.root)
    def test_design_schema_error_precedes_file_or_worker(self):
        with self.assertRaisesRegex(ValueError,'input.pdb'):
            design({'structure':str(self.path)},self.context)
        with self.assertRaisesRegex(ValueError,'input.chain'): validate_request({'pdb':str(self.path)})
        validate_request({'pdb':str(self.path),'chain':'A'})
    def test_design_rejects_unknown_functional_objective(self):
        with self.assertRaisesRegex(ValueError,'PAM'): validate_request({'pdb':str(self.path),'chain':'A','pam':'NGN'})


if __name__=='__main__':unittest.main()
