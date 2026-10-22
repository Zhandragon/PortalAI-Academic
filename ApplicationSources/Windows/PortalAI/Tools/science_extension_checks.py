"""Public readiness checks; no input data, service launches or large asset scans."""
from pathlib import Path

GROUPS={
 'Workbook/PDF input':('Scientific/table_workbook.py','Scientific/paper_context.py','Runtime/ScienceExtras/packages/openpyxl/__init__.py','Runtime/ScienceExtras/packages/pypdf/__init__.py'),
 'Molecular screening/docking':('Scientific/molecular_screening.py','Tools/ScienceExtras/vina.exe'),
 'Sequence specificity':('Scientific/sequence_screening.py',),
 'Printable CAD/support slicing':('Scientific/engineering_extensions.py','Tools/PrusaSlicer/prusa-slicer-console.exe'),
 'Transistor SPICE/PCB':('Scientific/circuit_extensions.py','Tools/KiCad/bin/ngspice.dll','Tools/KiCad/bin/kicad-cli.exe'),
 'Physics Lab (rigid/fluid/thermal/particles)':('Scientific/world_scene.py','Scientific/world_scene.html','Scientific/world_physics.js','Scientific/world_ui.js','Scientific/world_schema.json','Scientific/world_examples.json','Scientific/vendor/three.cjs','Scientific/vendor/cannon-es.cjs'),
}

def rows(root):
    root=Path(root);result=[]
    for label,paths in GROUPS.items():
        missing=[p for p in paths if not (root/p).is_file()]
        result.append({'status':'WARN' if missing else 'PASS','label':'Science extensions · '+label,
                       'detail':'Missing: '+', '.join(missing) if missing else 'Required public files present; availability only, not scientific or printer validation.'})
    try:
        import sys
        if str(root) not in sys.path:sys.path.insert(0,str(root))
        from Scientific.plannotate_tool import inventory
        data=inventory(root)
        result.append({'status':'PASS','label':'pLannotate DNA/protein assets',
                       'detail':f"{len(data['files'])} pinned paths/sizes present; SnapGene/FPbase/Swiss-Prot. No inference or full checksum scan in routine diagnostics."})
    except Exception as exc:
        result.append({'status':'WARN','label':'pLannotate DNA/protein assets','detail':str(exc)})
    result.append({'status':'WARN','label':'pLannotate RNA coverage','detail':'Rfam/Infernal is not packaged on Windows; RNA-family annotation remains unavailable.'})
    return result
