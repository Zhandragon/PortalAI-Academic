"""Explicit engineering assumptions, portable slicing and air-drag trajectories."""
import io,json,math,zipfile,xml.etree.ElementTree as ET
from Scientific.extensions_common import number,integer,keys,read,sha,asset,worker

def integrity(p,context):
    keys(p,{'members','safety_factor'})
    members=p['members'];sf=number(p.get('safety_factor',2),'safety_factor',1,100)
    if not isinstance(members,list) or not 1<=len(members)<=256:raise ValueError('Supply 1..256 members')
    rows=[]
    for m in members:
        context.check()
        if set(m)-{'name','length_m','area_m2','I_m4','c_m','E_Pa','yield_Pa','axial_force_N','moment_Nm','effective_length_factor','fatigue'}:raise ValueError('Unknown member parameter')
        L=number(m['length_m'],'length',1e-6,1e6);A=number(m['area_m2'],'area',1e-15,1e6);I=number(m['I_m4'],'I',1e-30,1e12);c=number(m['c_m'],'c',1e-9,1e4);E=number(m['E_Pa'],'E',1,1e15);y=number(m['yield_Pa'],'yield',1,1e13)
        N=number(m.get('axial_force_N',0),'axial');M=number(m.get('moment_Nm',0),'moment');K=number(m.get('effective_length_factor',1),'K',.1,10)
        stress=abs(N)/A+abs(M)*c/I;critical=math.pi**2*E*I/(K*L)**2
        yield_util=sf*stress/y;buckling_util=sf*max(0,-N)/critical
        row={'name':str(m.get('name',len(rows)))[:100],'maximum_normal_stress_Pa':stress,'yield_utilization':yield_util,'Euler_critical_compression_N':critical,'buckling_utilization':buckling_util,'Euler_slenderness_KL_over_r':K*L/math.sqrt(I/A),'assumptions':'Linear elastic prismatic member. Positive axial force is tension. Bending about supplied I, c. Euler buckling assumes a sufficiently slender perfect column.'}
        if m.get('fatigue'):
            f=m['fatigue']
            if set(f)!={'alternating_stress_Pa','mean_stress_Pa','endurance_limit_Pa','ultimate_Pa'}:raise ValueError('Fatigue needs alternating, mean, endurance and ultimate stresses in Pa')
            sa=number(f['alternating_stress_Pa'],'alternating stress',0);sm=number(f['mean_stress_Pa'],'mean stress');se=number(f['endurance_limit_Pa'],'endurance limit',1);su=number(f['ultimate_Pa'],'ultimate',1)
            row['Goodman_utilization']=sf*(sa/se+max(sm,0)/su)
        row['screen_flags']=[key for key in ('yield_utilization','buckling_utilization','Goodman_utilization') if row.get(key,0)>1]
        rows.append(row)
    rows.sort(key=lambda r:max(r.get(k,0) for k in ('yield_utilization','buckling_utilization','Goodman_utilization')),reverse=True)
    return {'members_ranked_by_utilization':rows,'safety_factor':sf,'limitations':['Screening under supplied loads/material data; not a full 3D FEA or certification.','Notch concentrations, joints, impact, anisotropic printed layers, creep and nonlinear/contact failure require additional modeling. Fatigue only uses supplied endurance data.','A value below one only passes these idealized checks; it does not establish safety.']},{}

def projectile(p,context):
    keys(p,{'position_m','velocity_m_s','mass_kg','area_m2','drag_coefficient','air_density_kg_m3','wind_m_s','gravity_m_s2','duration_s','points'})
    import numpy as np
    from scipy.integrate import solve_ivp
    def vector(v,name):
        if len(v)!=3:raise ValueError(name+' needs 3 coordinates')
        return np.array([number(x,name,-1e5,1e5) for x in v])
    pos=vector(p.get('position_m',[0,0,1]),'position');vel=vector(p['velocity_m_s'],'velocity');wind=vector(p.get('wind_m_s',[0,0,0]),'wind')
    if pos[2]<=0:raise ValueError('Start above ground z=0')
    mass=number(p['mass_kg'],'mass',1e-6,1e8);area=number(p['area_m2'],'area',0,1e6);cd=number(p.get('drag_coefficient',.47),'Cd',0,10);rho=number(p.get('air_density_kg_m3',1.225),'density',0,10000);g=number(p.get('gravity_m_s2',9.80665),'gravity',0,1000);duration=number(p.get('duration_s',30),'duration',.001,600);points=integer(p.get('points',301),'points',2,2000)
    def ode(t,y):
        context.check();relative=y[3:]-wind;a=-.5*rho*cd*area/mass*np.linalg.norm(relative)*relative;a[2]-=g;return np.r_[y[3:],a]
    def ground(t,y):return y[2]
    ground.terminal=True;ground.direction=-1
    solution=solve_ivp(ode,[0,duration],np.r_[pos,vel],rtol=1e-7,atol=1e-9,events=ground,dense_output=True,max_step=duration/100)
    if not solution.success:raise RuntimeError(solution.message)
    end=float(solution.t[-1]);times=np.linspace(0,end,points);states=solution.sol(times)
    rows=[{'t_s':float(t),'position_m':states[:3,i].tolist(),'velocity_m_s':states[3:,i].tolist()} for i,t in enumerate(times)]
    return {'trajectory':rows,'ground_impact':bool(len(solution.t_events[0])),'duration_s':end,'last_position_m':states[:3,-1].tolist(),'model':'3D point mass, constant gravity, quadratic relative-air drag and uniform wind','limitations':['Constant Cd/air density; no lift, tumbling, compressibility, variable atmosphere or fluid-field solution.']},{}

def mesh(p,context):
    import trimesh,numpy as np
    data=read(context,p['file'],16*1024**2);extension=str(p['file']).rsplit('.',1)[-1].lower()
    if extension not in ('stl','obj','ply'):raise ValueError('Mesh must be STL, OBJ or PLY')
    obj=trimesh.load(io.BytesIO(data),file_type=extension,force='mesh',process=True)
    if not isinstance(obj,trimesh.Trimesh) or not 1<=len(obj.faces)<=200000:raise ValueError('Mesh requires 1..200000 triangles')
    if not np.isfinite(obj.vertices).all():raise ValueError('Mesh has nonfinite vertices')
    if p.get('units','mm')!='mm':raise ValueError('Explicit millimetre mesh coordinates required')
    obj.apply_translation([0,0,-obj.bounds[0,2]])
    angle=number(p.get('overhang_degrees',45),'overhang',5,85)
    downward=(obj.face_normals[:,2]<-math.cos(math.radians(angle)))&(obj.triangles_center[:,2]>.1)
    report={'input_sha256':sha(data),'units':'mm','triangles':len(obj.faces),'watertight':bool(obj.is_watertight),'consistent_winding':bool(obj.is_winding_consistent),'bounds_mm':obj.bounds.tolist(),'volume_mm3':float(obj.volume) if obj.is_watertight else None,'downward_overhang_area_mm2':float(obj.area_faces[downward].sum()),'overhang_degrees_from_downward_vertical':angle,'limitations':['Overhang screening does not measure thin walls, self-intersections, strength or bed adhesion. Orientation is unchanged except bottom placed at z=0.','Printer, nozzle, material and process settings must be checked before printing.']}
    return obj,report

def print_prepare(p,context):
    keys(p,{'file','units','overhang_degrees','support_style','layer_height_mm'})
    obj,report=mesh(p,context)
    style=p.get('support_style','organic')
    if style not in ('organic','grid','snug'):raise ValueError('support_style organic/grid/snug')
    layer=number(p.get('layer_height_mm',.2),'layer_height',.05,.4)
    if not report['watertight'] or not report['consistent_winding']:raise ValueError('Repair non-watertight or inconsistently wound mesh before preparing print project')
    # Standards-based 3MF geometry plus PrusaSlicer support configuration; printer remains explicit.
    ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02';ET.register_namespace('',ns)
    model=ET.Element('{'+ns+'}model',unit='millimeter');resources=ET.SubElement(model,'resources');o=ET.SubElement(resources,'object',id='1',type='model');m=ET.SubElement(o,'mesh');vertices=ET.SubElement(m,'vertices');triangles=ET.SubElement(m,'triangles')
    for x,y,z in obj.vertices:ET.SubElement(vertices,'vertex',x=str(x),y=str(y),z=str(z))
    for a,b,c in obj.faces:ET.SubElement(triangles,'triangle',v1=str(a),v2=str(b),v3=str(c))
    ET.SubElement(ET.SubElement(model,'build'),'item',objectid='1')
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr('3D/3dmodel.model',ET.tostring(model,encoding='utf-8',xml_declaration=True))
        z.writestr('Metadata/Slic3r_PE.config',f'; generated by PortalAI\n; support_material = 1\n; support_material_auto = 1\n; support_material_style = {style}\n; layer_height = {layer}\n')
    report.update(supports={'enabled':True,'style':style,'stage':'Generated during slicing; 3MF contains model and support settings, not precomputed support geometry'},printer_profile_required=True)
    return report,{'supported-project.3mf':buffer.getvalue(),'model.stl':obj.export(file_type='stl')}

def slice_print(p,context):
    keys(p,{'file','profile','units','overhang_degrees'})
    obj,report=mesh(p,context)
    if not report['watertight'] or not report['consistent_winding']:raise ValueError('Slicing requires a closed consistently wound mesh')
    profile=read(context,p['profile'],1024**2).decode('utf-8-sig')
    # Exported settings are data, but slicer post-process commands are executable.
    parsed={}
    for line in profile.splitlines():
        if line.strip().startswith(('#',';','[')) or '=' not in line:continue
        k,v=line.split('=',1);k=k.strip();v=v.strip()
        if k in ('post_process','print_host','printhost_apikey','printhost_cafile','printhost_user','printhost_password') and v.strip('"'):
            raise ValueError('Remove slicer post-processing and printer network credentials before local slicing')
        parsed[k]=v
    if parsed.get('post_process',''):raise ValueError('Slicer post_process commands are not allowed')
    required=('bed_shape','nozzle_diameter','filament_diameter','temperature','bed_temperature','gcode_flavor','start_gcode','end_gcode')
    if any(k not in parsed for k in required):raise ValueError('Export a complete printer/material print configuration from PrusaSlicer; missing '+','.join(k for k in required if k not in parsed))
    for k in ('print_host','printhost_apikey','printhost_cafile','printhost_user','printhost_password'):
        if parsed.get(k,''):raise ValueError('Remove printer host/network credentials from the slicer profile')
    exe=asset(context,'Tools/PrusaSlicer/prusa-slicer-console.exe')
    result,contents=worker(context,'slice',{'exe':str(exe)}, {'model.stl':obj.export(file_type='stl'),'profile.ini':profile.encode()},timeout=100)
    result.update(profile_sha256=sha(profile.encode()),printer_configuration=parsed.get('printer_settings_id','explicit supplied profile'),material_configuration=parsed.get('filament_settings_id','explicit supplied profile'),preflight=report,limitations=['G-code is generated only; nothing is sent to a printer. Preview toolpaths and verify temperatures, machine limits, material compatibility and support removal.'])
    return result,contents
