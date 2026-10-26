"""Owned, gated science worker. Never accepts arbitrary shell commands or SPICE scripts."""
import ctypes as C,json,os,subprocess,sys
from pathlib import Path

def spice(p,folder):
    handles=[]
    if hasattr(os,'add_dll_directory'):handles.append(os.add_dll_directory(str(Path(p['dll']).parent)))
    dll=C.CDLL(p['dll']);logs=[]
    message=C.CFUNCTYPE(C.c_int,C.c_char_p,C.c_int,C.c_void_p)
    exitcb=C.CFUNCTYPE(C.c_int,C.c_int,C.c_bool,C.c_bool,C.c_int,C.c_void_p)
    callback=message(lambda text,i,u:logs.append(text.decode(errors='replace')) or 0)
    exit_callback=exitcb(lambda *args:0)
    dll.ngSpice_Init.argtypes=[message,message,exitcb,C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p];dll.ngSpice_Init.restype=C.c_int
    if dll.ngSpice_Init(callback,callback,exit_callback,None,None,None,None)!=0:raise RuntimeError('ngspice initialization failed')
    data=(folder/'circuit.cir').read_text().splitlines();lines=(C.c_char_p*(len(data)+1))(*[x.encode() for x in data],None)
    dll.ngSpice_Circ.argtypes=[C.POINTER(C.c_char_p)];dll.ngSpice_Circ.restype=C.c_int
    dll.ngSpice_Command.argtypes=[C.c_char_p];dll.ngSpice_Command.restype=C.c_int
    if dll.ngSpice_Circ(lines)!=0:raise RuntimeError('ngspice rejected circuit: '+'\n'.join(logs)[-1200:])
    command='op' if p['analysis']=='op' else f'tran {p["step"]} {p["duration"]}'
    if dll.ngSpice_Command(command.encode())!=0:raise RuntimeError('ngspice analysis failed: '+'\n'.join(logs)[-1200:])
    class Vec(C.Structure):
        _fields_=[('name',C.c_char_p),('type',C.c_int),('flags',C.c_short),('real',C.POINTER(C.c_double)),('complex',C.c_void_p),('length',C.c_int)]
    dll.ngGet_Vec_Info.argtypes=[C.c_char_p];dll.ngGet_Vec_Info.restype=C.POINTER(Vec)
    result={}
    for name in (['time'] if p['analysis']=='transient' else [])+['v('+n+')' for n in p['outputs']]:
        ptr=dll.ngGet_Vec_Info(name.encode())
        if not ptr or not ptr.contents.real or not 1<=ptr.contents.length<=100000:raise RuntimeError('ngspice produced no bounded real vector '+name+': '+'\n'.join(logs)[-800:])
        v=ptr.contents;stride=max(1,(v.length+1999)//2000);indexes=list(range(0,v.length,stride))
        if indexes[-1]!=v.length-1:indexes.append(v.length-1)
        result[name]=[v.real[i] for i in indexes]
    return {'analysis':p['analysis'],'vectors':result,'sample_note':'Adaptive ngspice time steps; long traces uniformly decimated to at most 2001 displayed samples','diagnostics':logs[-8:]}

def main():
    request=Path(sys.argv[1]).resolve();folder=request.parent;p=json.loads(request.read_text());root=Path(p['root']);operation=p['operation']
    if operation=='plannotate':
        sys.path.insert(0,str(root))
        from Scientific.plannotate_tool import execute_worker
        result=execute_worker(p,folder,root)
    elif operation=='pdf':
        sys.path.insert(0,str(root/'Runtime/ScienceExtras/packages'))
        from pypdf import PdfReader
        reader=PdfReader(folder/'paper.pdf',strict=True)
        if reader.is_encrypted:raise ValueError('Encrypted PDF requires a separately authorized, unlocked copy')
        if len(reader.pages)>200:raise ValueError('PDF exceeds 200 pages; select a section')
        sections=[];total=0
        for i,page in enumerate(reader.pages):
            content=page.get_contents()
            if content is not None and len(content.get_data())>8*1024**2:raise ValueError('PDF page content exceeds 8 MiB')
            text=page.extract_text() or '';total+=len(text)
            if total>2000000:raise ValueError('Extracted PDF text exceeds 2 million characters')
            if text.strip():sections.append(('Page '+str(i+1),text))
        if not sections:raise ValueError('PDF has no readable text layer; OCR is not included')
        result={'sections':sections,'pages':len(reader.pages)}
    elif operation=='spice':result=spice(p,folder)
    elif operation=='dock':
        cmd=[p['exe'],'--receptor','receptor.pdbqt','--ligand','ligand.pdbqt','--out','poses.pdbqt','--cpu','2','--seed',str(p['seed']),'--exhaustiveness',str(p['exhaustiveness']),'--num_modes',str(p['modes'])]
        for key in ('center','size'):
            for axis,value in zip('xyz',p[key]):cmd.extend(['--'+key+'_'+axis,str(value)])
        run=subprocess.run(cmd,cwd=folder,capture_output=True,text=True,timeout=95,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if run.returncode:raise RuntimeError((run.stdout+run.stderr)[-1500:])
        scores=[]
        for line in (folder/'poses.pdbqt').read_text().splitlines():
            if line.startswith('REMARK VINA RESULT:'):scores.append([float(v) for v in line.split(':',1)[1].split()])
        if not scores:raise RuntimeError('Vina returned no scored poses')
        result={'engine':'AutoDock Vina 1.2.7','poses':[{'score_kcal_mol':r[0],'rmsd_lower_angstrom':r[1],'rmsd_upper_angstrom':r[2]} for r in scores],'seed':p['seed']}
    elif operation=='slice':
        cmd=[p['exe'],'--datadir',str(folder),'--load','profile.ini','--support-material','--export-gcode','--output','print.gcode','model.stl']
        run=subprocess.run(cmd,cwd=folder,capture_output=True,text=True,timeout=95,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if run.returncode or not(folder/'print.gcode').is_file():raise RuntimeError((run.stdout+run.stderr)[-1500:])
        content=(folder/'print.gcode').read_text(errors='replace')
        result={'engine':'PrusaSlicer 2.9.4','gcode_bytes':len(content.encode()),'support_paths_present':';TYPE:Support material' in content,'printer_contacted':False,'summary':run.stdout[-1000:]}
    else:raise ValueError('Unknown isolated science operation')
    with (folder/'result.json').open('x',encoding='utf-8') as f:json.dump(result,f,allow_nan=False)
if __name__=='__main__':main()
