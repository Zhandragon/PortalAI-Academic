"""One operation catalog shared by native chat and the registered science CLI."""
HELP={
 'science.extensions':'Input schemas for lightweight science additions. All models report assumptions; no automatic scientific safety clearance.',
 'table.read':'path:.xlsx/.xlsm, sheet:name or 0-based index, max_rows<=100000, preview_rows<=100. First row is unique column names. use_cached_formulas:true only after Excel recalculation. No macros/formula execution; legacy .xls not supported.',
 'chem.screen':'smiles:string or list<=32. RDKit PAINS/BRENK/NIH alerts, SA complexity 1 easy..10 hard, QED/descriptors. Screening flags, not toxicity/efficacy or synthesis proof.',
 'binding.fit':'concentrations:[>=5], response:[same length], concentration_unit:M|mM|uM|nM|pM. One-site increasing equilibrium fit returns Kd and uncertainty from measurements.',
 'binding.dock':'receptor:prepared .pdbqt, ligand:prepared .pdbqt, center:[x,y,z], size:[x,y,z] Angstrom (1..30 each), exhaustiveness:1..16 default4, seed:1, modes<=9. CPU Vina; scores/poses, not measured affinity or protein-DNA/PAM prediction.',
 'protein.interface':'file:PDB/mmCIF, chain_a,chain_b:author IDs, cutoff:1..8 Angstrom default4. First model heavy-atom/residue contacts; no affinity prediction.',
 'genome.specificity':'reference:local FASTA <=6GiB, queries:[{name,sequence:15..80 ACGT,optional pam:3-prime IUPAC <=8}], mismatches:0..3, optional primer_pair:[two names], max_amplicon<=100000. Streaming both strands, substitution-only, complete scanned-reference report or failure. No uploaded sequence. May take minutes.',
 'genome.annotate':'Default pLannotate DNA/protein homology annotation: sequence:20..100000 ACGTN bases or file:single FASTA/GenBank, circular:true(default for FASTA; GenBank topology respected), mode:standard|fast, name. Standard uses SnapGene/FPbase/Swiss-Prot, fast omits Swiss-Prot; Rfam RNA search unavailable. Local Windows CPU, no sequence upload. Exports annotated.gb, features.csv and feature-map.svg. Legacy features:[{name,sequence,role,source}] selects exact supplied-reference matching; never invent a catalog for automatic annotation.',
 'paper.context':'Exactly one pmid, pmcid:PMC..., file:PDF (text layer <=200 pages)/UTF8 text/JATS XML, or text; query, max_characters:1000..24000 default8000. PubMed abstracts or PMC OA full-text passages; ranked verbatim chunks with source/offsets, full evidence.json. No OCR, invented findings or paywall bypass.',
 'mechanical.integrity':'members:[{name,length_m,area_m2,I_m4,c_m,E_Pa,yield_Pa,axial_force_N:positive tension,moment_Nm,effective_length_factor,optional fatigue:{alternating_stress_Pa,mean_stress_Pa,endurance_limit_Pa,ultimate_Pa}}], safety_factor default2. Idealized yield/Euler buckling/Goodman screening.',
 'cad.print_prepare':'file:STL/OBJ/PLY in mm, support_style:organic|grid|snug, layer_height_mm:.05..0.4, overhang_degrees:45. Mesh checks, STL and support-enabled 3MF project; supports generated when sliced with a printer/material profile.',
 'cad.slice':'file:STL/OBJ/PLY mm, profile:complete exported PrusaSlicer INI for exact printer/material. Produces G-code with supports, no printer communication. Post-process commands/network credentials refused. Inspect toolpaths before printing.',
 'electrical.spice':'components:[{ref:R/C/L/V/I/D/Q/M...,nodes:[pins in SPICE order],value:SI,model:name,pulse:[low,high,delay,rise,fall,width,period]}], models:[{name,type:D|NPN|PNP|NMOS|PMOS,parameters:numeric model values}], analysis:op|transient,step_s,duration_s<=10,outputs:[node names]. Node 0 ground; BJT C/B/E, MOS D/G/S/B. No arbitrary netlist commands.',
 'electrical.board':'width_mm,height_mm,components:[{ref,value,x_mm,y_mm,datasheet,pads:[{number,net,function,dx_mm,dy_mm,diameter_mm,drill_mm}]}], optional tracks:[{net,start_mm:[x,y],end_mm:[x,y],width_mm,layer:F.Cu|B.Cu}]. Editable KiCad board and BOM; explicit transistor pin mapping, requires DRC/routing review.',
 'physics.projectile_drag':'position_m:[x,y,z>0],velocity_m_s:[x,y,z],mass_kg,area_m2,drag_coefficient:.47,air_density_kg_m3:1.225,wind_m_s:[x,y,z],gravity_m_s2:9.80665,duration_s<=600,points<=2000. Ground z=0; quadratic drag.',
 'physics.world_schema':'Full bounded Physics Lab JSON schema, examples and limitations; call this before constructing mechanisms/fluids/thermal scenes. No input required.',
 'physics.world':'Offline interactive Physics Lab: objects<=96 (box/sphere, SI units, Y up), wind, connections (spring/rope/pulley/weld, break thresholds), bulk liquid buoyancy, SPH fluids<=256 particles, heaters/lumped heat, finite-fuel fire, pre-cut box breakage, visual emitters. Use physics.world_schema for exact fields and examples. Outputs world.html and scene.json with controls/presets/save/load. Manual radial impulse burst is a visual/rigid demo, never combustion/blast/CFD/structural prediction.'
}

def run(operation,p,context):
    if operation=='science.extensions':return {'operations':HELP},{}
    if operation=='table.read':
        from Scientific.table_workbook import run
        return run(p,context)
    if operation in ('chem.screen','binding.fit','binding.dock','protein.interface'):
        from Scientific import molecular_screening as m
        return {'chem.screen':m.screen,'binding.fit':m.affinity,'binding.dock':m.dock,'protein.interface':m.interface}[operation](p,context)
    if operation in ('genome.specificity','genome.annotate'):
        from Scientific import sequence_screening as m
        return (m.specificity if operation=='genome.specificity' else m.annotate)(p,context)
    if operation=='paper.context':
        from Scientific.paper_context import run
        return run(p,context)
    if operation in ('mechanical.integrity','physics.projectile_drag','cad.print_prepare','cad.slice'):
        from Scientific import engineering_extensions as m
        return {'mechanical.integrity':m.integrity,'physics.projectile_drag':m.projectile,'cad.print_prepare':m.print_prepare,'cad.slice':m.slice_print}[operation](p,context)
    if operation in ('electrical.spice','electrical.board'):
        from Scientific import circuit_extensions as m
        return (m.simulate if operation=='electrical.spice' else m.board)(p,context)
    if operation=='physics.world_schema':
        from Scientific.extensions_common import keys
        from Scientific.world_scene import describe
        keys(p,set())
        return describe(),{}
    if operation=='physics.world':
        from Scientific.world_scene import run
        return run(p,context)
    raise ValueError('Unknown science extension')
