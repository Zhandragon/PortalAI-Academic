"""Transparent molecular alerts, synthetic accessibility and prepared-pose docking."""
import json,math
from Scientific.extensions_common import number,integer,keys,read,sha,asset,worker

def screen(p,context):
    keys(p,{'smiles'})
    from rdkit import Chem
    from rdkit.Chem import Descriptors,Lipinski,Crippen,QED,FilterCatalog
    from rdkit.Contrib.SA_Score import sascorer
    items=p['smiles'] if isinstance(p.get('smiles'),list) else [p.get('smiles')]
    if not 1<=len(items)<=32:raise ValueError('Supply 1..32 SMILES strings')
    catalogs=[]
    for name in ('PAINS','BRENK','NIH'):
        params=FilterCatalog.FilterCatalogParams();params.AddCatalog(getattr(FilterCatalog.FilterCatalogParams.FilterCatalogs,name))
        catalogs.append((name,FilterCatalog.FilterCatalog(params)))
    rows=[]
    for value in items:
        context.check()
        if not isinstance(value,str) or not 1<=len(value)<=4000:raise ValueError('SMILES must be 1..4000 characters')
        m=Chem.MolFromSmiles(value)
        if m is None or not 1<=m.GetNumHeavyAtoms()<=256:raise ValueError('Invalid SMILES or more than 256 heavy atoms')
        alerts=[{'catalog':name,'alert':match.GetDescription()} for name,cat in catalogs for match in cat.GetMatches(m)]
        rows.append({'canonical_smiles':Chem.MolToSmiles(m),'molecular_weight':Descriptors.MolWt(m),'logP':Crippen.MolLogP(m),'TPSA':Descriptors.TPSA(m),'HBD':Lipinski.NumHDonors(m),'HBA':Lipinski.NumHAcceptors(m),'rotatable_bonds':Lipinski.NumRotatableBonds(m),'fraction_CSP3':Lipinski.FractionCSP3(m),'QED':QED.qed(m),'synthetic_accessibility_1_easy_10_hard':sascorer.calculateScore(m),'structural_alerts':alerts,'no_alerts_is_not_safety':True})
    return {'molecules':rows,'methods':['RDKit PAINS, BRENK and NIH structural-alert catalogs','Ertl/Schuffenhauer synthetic-accessibility heuristic'],
            'limitations':['Alerts flag patterns for review, not toxicity, dose safety or efficacy. Absence of alerts is not clearance.','SA estimates complexity; it does not propose a synthesis route, price, yield or practical feasibility.','QED and Lipinski-style descriptors are not binding affinity.']},{}

def affinity(p,context):
    keys(p,{'concentrations','response','concentration_unit','model'})
    import numpy as np
    from scipy.optimize import curve_fit
    if p.get('model','one_site')!='one_site':raise ValueError('Only one_site equilibrium binding is supported')
    unit=p.get('concentration_unit')
    if unit not in ('M','mM','uM','nM','pM'):raise ValueError('Specify concentration_unit M/mM/uM/nM/pM')
    x=np.array([number(v,'concentration',0,1e15) for v in p['concentrations']]);y=np.array([number(v,'response') for v in p['response']])
    if not 5<=len(x)<=10000 or x.shape!=y.shape or len(set(x))<4 or x.max()<=0:raise ValueError('Need >=5 paired observations at >=4 distinct concentrations')
    if np.ptp(y)==0:raise ValueError('Constant response cannot identify affinity')
    scale=float(x.max());xs=x/scale
    def f(c,b,a,k):return b+a*c/(k+c)
    params,cov=curve_fit(f,xs,y,p0=[float(y[x.argmin()]),float(np.ptp(y)),.2],bounds=([-np.inf,0,1e-12],[np.inf,np.inf,1e6]),maxfev=10000)
    pred=f(xs,*params);kd=float(params[2]*scale);se=float(np.sqrt(cov[2,2])*scale)
    if not math.isfinite(kd) or not math.isfinite(se):raise ValueError('Fit is not identifiable; acquire measurements spanning saturation')
    return {'Kd':kd,'Kd_standard_error':se,'concentration_unit':unit,'baseline':float(params[0]),'Bmax_above_baseline':float(params[1]),'residual_RMSE':float(np.sqrt(np.mean((y-pred)**2))),'observed':y.tolist(),'predicted':pred.tolist(),'warnings':(['Kd outside measured range; extrapolation is poorly constrained'] if not x.min()<kd<x.max() else [])+(['Large uncertainty; affinity is poorly constrained'] if se>kd/2 else []),'limitations':['Fit assumes equilibrium, one independent binding site, increasing response, and negligible ligand depletion.','This estimates affinity from supplied experimental measurements, not from a sequence or docking score. No automatic assay-quality assessment.']},{}

def dock(p,context):
    keys(p,{'receptor','ligand','center','size','exhaustiveness','seed','modes','timeout'})
    center=p['center'];size=p['size']
    if len(center)!=3 or len(size)!=3:raise ValueError('center and size need three Angstrom coordinates')
    center=[number(v,'center',-10000,10000) for v in center];size=[number(v,'size',1,30) for v in size]
    receptor=read(context,p['receptor'],8*1024**2);ligand=read(context,p['ligand'],1024**2)
    for name,data in [('receptor',receptor),('ligand',ligand)]:
        text=data.decode('ascii')
        if not any(line.startswith(('ATOM  ','HETATM')) for line in text.splitlines()):raise ValueError(name+' must be prepared PDBQT, with charges and atom types')
    if b'ROOT' not in ligand or b'TORSDOF' not in ligand:raise ValueError('Ligand requires a prepared PDBQT torsion tree')
    exe=asset(context,'Tools/ScienceExtras/vina.exe')
    request={'exe':str(exe),'center':center,'size':size,'exhaustiveness':integer(p.get('exhaustiveness',4),'exhaustiveness',1,16),'seed':integer(p.get('seed',1),'seed',1,2147483647),'modes':integer(p.get('modes',5),'modes',1,9)}
    result,contents=worker(context,'dock',request,{'receptor.pdbqt':receptor,'ligand.pdbqt':ligand},timeout=integer(p.get('timeout',90),'timeout',5,100))
    result.update(receptor_sha256=sha(receptor),ligand_sha256=sha(ligand),center_angstrom=center,size_angstrom=size,
                  limitations=['Vina 1.2.7 empirical docking scores in kcal/mol are ranking proxies, not measured Kd or binding free energy.','Requires scientifically prepared receptor/ligand PDBQT and a specified binding box. No protonation/metal/water repair is inferred.','Rigid receptor small-molecule docking; not protein-protein, protein-DNA/PAM, toxicity or efficacy prediction.'])
    return result,contents

def interface(p,context):
    keys(p,{'file','chain_a','chain_b','cutoff'})
    from Scientific.protein_structure import load
    # Use the same bounded structure reader and author-chain convention.
    from Bio.PDB import PDBParser,MMCIFParser
    from scipy.spatial import cKDTree
    import io
    data=read(context,p['file'],20*1024**2);text=data.decode('utf-8-sig')
    parser=MMCIFParser(QUIET=True) if text.lstrip().startswith('data_') else PDBParser(QUIET=True,PERMISSIVE=False)
    model=next(iter(parser.get_structure('interface',io.StringIO(text))))
    a=str(p['chain_a']);b=str(p['chain_b'])
    if a==b or a not in model or b not in model:raise ValueError('Select two distinct existing author chain IDs')
    atoms=[[atom for atom in model[c].get_atoms() if atom.element not in ('H','D')] for c in (a,b)]
    if not all(0<len(group)<=100000 for group in atoms):raise ValueError('Each chain needs 1..100000 heavy atoms')
    cutoff=number(p.get('cutoff',4),'cutoff',1,8);tree=cKDTree([x.coord for x in atoms[1]]);pairs={};count=0
    for i,atom in enumerate(atoms[0]):
        if i%256==0:context.check()
        for j in tree.query_ball_point(atom.coord,cutoff):
            other=atoms[1][j];count+=1
            if count>1000000:raise ValueError('Contact count exceeds limit')
            k=(str(atom.parent.id),str(other.parent.id));d=float(((atom.coord-other.coord)**2).sum()**.5)
            pairs[k]=min(pairs.get(k,float('inf')),d)
    rows=[{'residue_a':k[0],'residue_b':k[1],'closest_angstrom':d} for k,d in sorted(pairs.items(),key=lambda x:x[1])]
    return {'input_sha256':sha(data),'chain_a':a,'chain_b':b,'cutoff_angstrom':cutoff,'heavy_atom_contacts':count,'residue_pairs':rows[:2000],'pairs_truncated':len(rows)>2000,'limitations':['Contacts describe this supplied pose only; proximity does not demonstrate affinity, specificity or functional effects. First model only; no solvent, energy or conformational sampling.']},{}
