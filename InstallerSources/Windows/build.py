"""Build the Windows installer with its complete embedded helper/resource set.

Requires Windows .NET Framework 4.x and the verified python-bootstrap.zip from
the matching installer release. The runtime ZIP is intentionally not Git-tracked.
"""
from pathlib import Path
import argparse, os, subprocess

RESOURCES = ('installer_core.py', 'engine_cli.py', 'installer_storage.py', 'portable_update.py', 'storage-plan.json')

def build(source, runtime_zip, output, icon=None):
    compiler=Path(os.environ['SystemRoot'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    resources=[(runtime_zip, 'python-bootstrap.zip')]+[(source/name,name) for name in RESOURCES]
    for path,name in resources:
        if not path.is_file():raise FileNotFoundError('Required embedded resource missing: '+name)
    command=[str(compiler), '/nologo','/target:winexe','/optimize+','/platform:anycpu','/out:'+str(output)]
    command+=['/r:'+name+'.dll' for name in ('System.Windows.Forms','System.Drawing','System.Web.Extensions','System.IO.Compression','System.IO.Compression.FileSystem')]
    command+=['/resource:'+str(path)+','+name for path,name in resources]
    if icon:command+=['/win32icon:'+str(icon)]
    command+=[str(source/'Installer.cs')]
    subprocess.run(command,check=True)
    subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass',
                    '-File',str(source/'check-resources.ps1'),'-Installer',str(output),
                    '-Sources',str(source),'-RuntimeZip',str(runtime_zip)],check=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-zip',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--icon',type=Path)
    args=parser.parse_args()
    build(Path(__file__).resolve().parent,args.runtime_zip.resolve(),args.output.resolve(),args.icon)
