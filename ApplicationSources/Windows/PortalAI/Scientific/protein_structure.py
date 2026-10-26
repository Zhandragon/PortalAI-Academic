"""Bounded PDB/mmCIF inspection and explicit sequence candidates; no inference."""
import hashlib
import io
import json
import math
import os
import re
import warnings

from Scientific.biology import AA, integer, protein_variants

MAX_BYTES = 20 * 1024**2
MAX_ATOMS = 200000
LIMITATIONS = [
    'Coordinate sequences contain only observed residues; missing loops are not reconstructed.',
    'Declared polymer sequences come from the supplied file, not a verified wild-type reference.',
    'Sequence substitutions do not rebuild side chains or predict folding, binding, PAM specificity or activity.',
]


def _aa(name):
    from Bio.Data.PDBData import protein_letters_3to1_extended
    return protein_letters_3to1_extended.get(name.strip().upper(), 'X')


def _declared_pdb(text):
    chains = {}
    expected = {}
    for line in text.splitlines():
        if line.startswith('SEQRES'):
            chain = line[11:12]
            n = int(line[13:17])
            if chain in expected and expected[chain] != n:
                raise ValueError('Inconsistent PDB SEQRES length')
            expected[chain] = n
            chains.setdefault(chain, []).extend(line[19:70].split())
    for chain, residues in chains.items():
        if len(residues) != expected[chain]:
            raise ValueError('Incomplete PDB SEQRES records for chain '+repr(chain))
    return {c: ''.join(map(_aa, names)) for c, names in chains.items()}


def _declared_cif(text):
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict
    d = MMCIF2Dict(io.StringIO(text))
    def columns(*keys):
        values = [d.get(key, []) for key in keys]
        if any(not isinstance(v, list) for v in values) or len({len(v) for v in values}) > 1:
            raise ValueError('Inconsistent mmCIF sequence columns')
        return zip(*values)
    entities = {}
    for eid, number, residue in columns('_entity_poly_seq.entity_id', '_entity_poly_seq.num', '_entity_poly_seq.mon_id'):
        position = int(number)
        current = entities.setdefault(eid, {})
        aa = _aa(residue)
        if position in current and current[position] != aa:
            raise ValueError('Ambiguous mmCIF polymer sequence')
        current[position] = aa
    sequences = {}
    for eid, positions in entities.items():
        if sorted(positions) != list(range(1, len(positions)+1)):
            raise ValueError('Incomplete mmCIF polymer sequence numbering')
        sequences[eid] = ''.join(positions[i] for i in sorted(positions))
    asym_entity = dict(columns('_struct_asym.id', '_struct_asym.entity_id'))
    auth_entities = {}
    for label, author in columns('_atom_site.label_asym_id', '_atom_site.auth_asym_id'):
        eid = asym_entity.get(label)
        if eid in sequences:
            auth_entities.setdefault(author, set()).add(eid)
    # Bind label-asym sequence entities to the author chain IDs used by the parser.
    # Never mistake label A for author A or choose between multiple entities.
    return {chain: sequences[next(iter(ids))] for chain, ids in auth_entities.items() if len(ids) == 1}


def load(p, context):
    from Bio.PDB import MMCIFParser, PDBParser
    from media_paths import media_reference
    context.check()
    supplied = [p[k] for k in ('file', 'input') if k in p]
    if len(supplied) != 1 or not isinstance(supplied[0], str) or not supplied[0].strip():
        raise ValueError('Provide one input.file path (legacy protein.inspect input.input is also accepted).')
    path = media_reference(context.root, supplied[0])
    with path.open('rb') as handle:
        before = os.fstat(handle.fileno())
        data = handle.read(MAX_BYTES+1)
        after = os.fstat(handle.fileno())
    context.check()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    # On bundled Windows Python, fstat ctime and path.stat ctime can describe
    # different timestamps. Compare ctime only between the same open handle.
    if identity(before) != identity(after) or before.st_ctime_ns != after.st_ctime_ns or identity(after) != identity(path.stat()):
        raise RuntimeError('Structure changed while being read; retry after the writer finishes.')
    if len(data) > MAX_BYTES:
        raise ValueError('Structure analysis supports at most 20 MiB.')
    text = data.decode('utf-8-sig')
    if '\x00' in text:
        raise ValueError('Expected a text PDB or mmCIF structure, not a binary file.')
    first = next((line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith('#')), '')
    cif = first.lower().startswith('data_')
    if not cif and not any(line.startswith(('ATOM  ', 'HETATM')) for line in text.splitlines()):
        raise ValueError('No PDB coordinate records or mmCIF data block found.')
    if not cif and sum(line.startswith(('ATOM  ', 'HETATM')) for line in text.splitlines()) > MAX_ATOMS:
        raise ValueError('Structure exceeds the 200,000 atom analysis limit.')
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        parser = MMCIFParser(QUIET=False, auth_chains=True, auth_residues=True) if cif else PDBParser(QUIET=False, PERMISSIVE=False)
        structure = parser.get_structure('input', io.StringIO(text))
    context.check()
    if sum(1 for _ in structure.get_atoms()) > MAX_ATOMS:
        raise ValueError('Structure exceeds the 200,000 atom analysis limit.')
    models = list(structure)
    index = integer(p.get('model_index', 0), 'model_index', 0, max(0, len(models)-1))
    if not models:
        raise ValueError('No coordinate models found.')
    declared = _declared_cif(text) if cif else _declared_pdb(text)
    return models[index], declared, {
        'input': str(path), 'input_sha256': hashlib.sha256(data).hexdigest(),
        'input_bytes': len(data), 'format': 'mmCIF' if cif else 'PDB',
        'model_count': len(models), 'model_index': index,
        'parser_warnings': [str(w.message)[:300] for w in caught[:20]],
    }


def inspect(p, context):
    from Bio.PDB import is_aa
    model, declared, result = load(p, context)
    selected = p.get('chain')
    if selected is not None and (not isinstance(selected, str) or selected not in model):
        raise ValueError('Select an existing author chain ID; available: '+', '.join(repr(c.id) for c in model))
    details = []
    for chain in model:
        context.check()
        if selected is not None and chain.id != selected: continue
        protein = []
        other = {}
        atom_count = 0
        gaps = []
        previous = None
        for res in chain:
            if len(protein) % 256 == 0: context.check()
            if not is_aa(res, standard=False) and not (res.id[0] == ' ' and all(a in res for a in ('N', 'CA', 'C'))):
                other[res.resname] = other.get(res.resname, 0)+1
                continue
            for atom in res:
                if not all(math.isfinite(float(x)) for x in atom.coord):
                    raise ValueError('Non-finite protein coordinates')
            row = {'number': res.id[1], 'insertion': res.id[2].strip(), 'resname': res.resname,
                   'aa': _aa(res.resname), 'missing_backbone_atoms': [a for a in ('N', 'CA', 'C', 'O') if a not in res],
                   'alternate_conformers': bool(res.is_disordered())}
            protein.append(row)
            atom_count += len(res)
            if previous is not None and res.id[1] > previous+1:
                gaps.append({'after': previous, 'before': res.id[1]})
            previous = res.id[1]
        if len(protein) > 10000: raise ValueError('Protein chains longer than 10,000 residues are not supported.')
        details.append({'chain': chain.id, 'observed_residues': len(protein), 'protein_atoms': atom_count,
                        'observed_sequence': ''.join(r['aa'] for r in protein),
                        'declared_sequence': declared.get(chain.id) if protein else None,
                        'residue_map': protein, 'numbering_gaps': gaps,
                        'other_residue_counts': other})
    context.check()
    result.update(chain_details=details, limitations=LIMITATIONS,
                  chains={c['chain']: c['observed_residues'] for c in details},
                  residues=sum(c['observed_residues'] for c in details),
                  atoms_standard_residues=sum(c['protein_atoms'] for c in details))
    return result


def _fasta(name, sequence):
    return '>'+name+'\n'+'\n'.join(sequence[i:i+80] for i in range(0, len(sequence), 80))+'\n'


def run(operation, p, context):
    allowed = {'file', 'input', 'chain', 'model_index', 'export', 'output_dir'}
    if operation == 'protein.structure_variants': allowed |= {'sequence_source', 'variants'}
    unknown = set(p)-allowed
    if unknown: raise ValueError('Unsupported structure arguments: '+', '.join(sorted(unknown))+'. See biology.help.')
    full = inspect(p, context)
    contents = {'structure.json': json.dumps(full, ensure_ascii=True, indent=2, allow_nan=False)}
    if operation == 'protein.inspect':
        summary = {k:v for k,v in full.items() if k != 'chain_details'}
        summary['chain_details'] = []
        fasta = ''
        for i, c in enumerate(full['chain_details']):
            entry = {k:v for k,v in c.items() if k not in ('observed_sequence', 'declared_sequence', 'residue_map')}
            entry['declared_length'] = len(c['declared_sequence']) if c['declared_sequence'] else None
            entry['incomplete_backbone_residues'] = sum(bool(r['missing_backbone_atoms']) for r in c['residue_map'])
            entry['alternate_conformer_residues'] = sum(r['alternate_conformers'] for r in c['residue_map'])
            summary['chain_details'].append(entry)
            for kind in ('declared', 'observed'):
                seq = c[kind+'_sequence']
                if seq: fasta += _fasta('chain_'+str(i+1)+'_'+kind, seq)
        if fasta: contents['structure-sequences.fasta'] = fasta
        summary['sequence_labels'] = 'FASTA chain_N follows chain_details order. Full sequences and author residue IDs are in structure.json.'
        return summary, contents
    if not isinstance(p.get('chain'), str) or len(full['chain_details']) != 1:
        raise ValueError('protein.structure_variants requires one explicit input.chain author ID.')
    chain = full['chain_details'][0]
    source = p.get('sequence_source', 'declared')
    if source not in ('declared', 'observed'): raise ValueError('sequence_source must be declared or observed.')
    reference = chain[source+'_sequence']
    if not reference or set(reference)-AA:
        raise ValueError('Selected sequence is absent or contains ambiguous/nonstandard residues. Inspect structure.json; no sequence is silently substituted.')
    variants = p.get('variants')
    if not isinstance(variants, list) or not 1 <= len(variants) <= 8:
        raise ValueError('Provide 1..8 variants with explicit substitutions; no functional target is inferred.')
    names = {'reference'}
    for v in variants:
        if not isinstance(v, dict) or set(v)-{'name', 'substitutions'}:
            raise ValueError('Each variant accepts only name and substitutions.')
        name = v.get('name')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,60}', name) or name in names:
            raise ValueError('Variant names must be unique letters/digits/underscore/hyphen, excluding reference.')
        names.add(name)
        if not isinstance(v.get('substitutions'), list) or not v['substitutions']:
            raise ValueError('Each candidate requires explicit amino-acid substitutions.')
    designed = protein_variants({'sequence':reference, 'variants':variants}, context.check)
    report = {**designed, 'input_sha256':full['input_sha256'], 'chain':p['chain'], 'sequence_source':source,
              'numbering':'1-based positions in the selected sequence; NOT PDB/mmCIF author residue numbers.',
              'limitations':LIMITATIONS+designed['limitations'], 'structure_rebuilt':False, 'function_validated':False}
    contents['candidate-sequences.fasta'] = ''.join(_fasta(v['name'], v['sequence']) for v in report['variants'])
    contents['candidate-report.json'] = json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False)
    context.check()
    summary = {**report, 'variants':[{k:v for k,v in row.items() if k != 'sequence'} for row in report['variants']]}
    summary['sequence_length'] = len(reference)
    return summary, contents
