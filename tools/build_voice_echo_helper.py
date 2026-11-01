"""Build a tiny static-runtime Windows DSP wrapper with an existing local SDK."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--build-dir',type=Path,required=True);a=p.parse_args();a.build_dir.mkdir(parents=True,exist_ok=True)
root=Path(__file__).resolve().parents[1]/'ApplicationSources/Windows/PortalAI/Tools';source=root/'VoiceEchoCapture.cpp';output=root/'voice_echo_capture.exe'
vs=Path(os.environ['ProgramFiles'])/'Microsoft Visual Studio/2022/Community/VC/Tools/MSVC'
toolchain=sorted(vs.iterdir())[-1];sdk=Path(os.environ['ProgramFiles(x86)'])/'Windows Kits/10';version=sorted((sdk/'Include').iterdir())[-1].name
compiler=toolchain/'bin/Hostx64/x64/cl.exe'
includes=[toolchain/'include',*(sdk/'Include'/version/k for k in ('ucrt','shared','um','winrt'))]
libraries=[toolchain/'lib/x64',*(sdk/'Lib'/version/k/'x64' for k in ('ucrt','um'))]
env=os.environ.copy();env.update(TEMP=str(a.build_dir),TMP=str(a.build_dir))
command=[str(compiler),'/nologo','/O2','/MT','/EHsc','/std:c++17',*['/I'+str(v) for v in includes],'/Fo'+str(a.build_dir/'voice_echo_capture.obj'),str(source),'/link','/OUT:'+str(output),*['/LIBPATH:'+str(v) for v in libraries],'ole32.lib','oleaut32.lib','winmm.lib','uuid.lib','wmcodecdspuuid.lib','strmiids.lib','msdmo.lib']
subprocess.run(command,cwd=a.build_dir,env=env,check=True)
sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
(root/'voice_echo_capture.json').write_text(json.dumps({'source':source.name,'source_sha256':sha(source),'file':output.name,'bytes':output.stat().st_size,'sha256':sha(output),'runtime':'Windows Voice Capture DSP; statically linked C++ runtime','reference':'https://learn.microsoft.com/windows/win32/medfound/voicecapturedmo'},indent=2))
print('Built '+str(output.stat().st_size)+' bytes')
