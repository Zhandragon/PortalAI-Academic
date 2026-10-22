"""Small synthetic CLI exports in the offline guest; no host designs or libraries."""
import subprocess
import sys
from pathlib import Path

ROOT=Path('/portable');sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'Scientific')]
from science_core import op_electrical_kicad_export,_find_kicad
from runtime_policy import portable_env
from linux_owned_run import run
from kicad_linux import command_environment

exe=_find_kicad(ROOT)
assert exe==str(ROOT/'Runtime/KiCad/linux-x64/bin/kicad-cli'),exe
version=run([exe,'version'],cwd=ROOT,env=portable_env(ROOT),memory_bytes=1024**3,timeout=25)
assert version.returncode==0,(version.stdout,version.stderr)
assert '9.0.2' in version.stdout,version.stdout
_,vendor_env=command_environment(ROOT)
assert (Path(vendor_env['KICAD9_SYMBOL_DIR'])/'Device.kicad_sym').is_file()
assert (Path(vendor_env['KICAD9_FOOTPRINT_DIR'])/'Resistor_SMD.pretty/R_0805_2012Metric.kicad_mod').is_file()
component=Path(vendor_env['KICAD9_3DMODEL_DIR'])/'Resistor_SMD.3dshapes/R_0805_2012Metric.step'
assert component.is_file(),component
folder=ROOT/'Outputs/kicad-fixture';folder.mkdir(parents=True,exist_ok=True)
sch=folder/'fixture.kicad_sch'
sch.write_text('''(kicad_sch (version 20230121) (generator eeschema)
 (uuid "c04fbcd2-f86c-41bb-810b-50bcbddc00fd") (paper "A4") (lib_symbols)
 (text "PortalAI Linux schematic export" (at 30 30 0)
  (effects (font (size 1.27 1.27)) (justify left))
  (uuid "6ccf2b5a-93ac-4468-9dfd-e65220673bed"))
 (sheet_instances (path "/" (page "1"))))''')
for kind in ('schematic-svg','bom'):
    result=op_electrical_kicad_export({'input':str(sch),'kind':kind},ROOT)
    files=list(Path(result['output_dir']).glob('*.svg' if kind=='schematic-svg' else '*.csv'))
    assert files and all(file.stat().st_size>0 for file in files),result
    if kind=='schematic-svg':assert '<svg' in files[0].read_text()
    print('KiCad '+kind+' actual private output passed',flush=True)
pcb=folder/'fixture.kicad_pcb'
pcb.write_text('''(kicad_pcb (version 20221018) (generator pcbnew)
 (general (thickness 1.6)) (paper "A4")
 (layers (0 "F.Cu" signal) (31 "B.Cu" signal) (44 "Edge.Cuts" user))
 (setup (pad_to_mask_clearance 0))
 (net 0 "")
 (footprint "Resistor_SMD:R_0805_2012Metric" (layer "F.Cu") (at 20 18)
  (attr smd)
  (fp_text reference "R1" (at 0 -2) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
  (fp_text value "1k" (at 0 2) (layer "F.Fab") (effects (font (size 1 1) (thickness 0.15))))
  (model "${KICAD9_3DMODEL_DIR}/Resistor_SMD.3dshapes/R_0805_2012Metric.step"
   (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0))))
 (gr_rect (start 10 10) (end 30 25) (stroke (width 0.1) (type default))
  (fill none) (layer "Edge.Cuts") (tstamp "caa1dede-577a-4e41-a456-095bde5c8e9c")))''')
result=op_electrical_kicad_export({'input':str(pcb),'kind':'pcb-step'},ROOT)
step=Path(result['output_dir'])/'fixture.step'
assert step.is_file() and step.stat().st_size>500,result
assert 'ISO-10303-21' in step.read_text(),result
assert 'R1' in step.read_text() or 'R_0805' in step.read_text(), 'Bundled component was missing from STEP assembly'
assert (ROOT/'Data/Science/KiCad/config').is_dir()
print('KiCad 9.0.2 STEP board + bundled resistor 3D component, symbols/footprints, loader/resources, and private config passed',flush=True)
