"""Build the tiny read-only helper with Windows' existing .NET compiler."""
import hashlib,json,os,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]/'ApplicationSources/Windows/PortalAI/Tools'
framework=Path(os.environ['SystemRoot'])/'Microsoft.NET/Framework64/v4.0.30319'
source=root/'AccessibilitySnapshot.cs';output=root/'accessibility_snapshot.exe'
subprocess.run([str(framework/'csc.exe'),'/nologo','/target:exe','/optimize+','/platform:anycpu','/out:'+str(output),
    '/r:'+str(framework/'WPF/UIAutomationClient.dll'),'/r:'+str(framework/'WPF/UIAutomationTypes.dll'),
    '/r:'+str(framework/'WPF/WindowsBase.dll'),'/r:System.Web.Extensions.dll',str(source)],check=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
(root/'accessibility_snapshot.json').write_text(json.dumps({'source':source.name,'source_sha256':sha(source),
    'file':output.name,'bytes':output.stat().st_size,'sha256':sha(output),'runtime':'Windows .NET Framework; no bundled runtime'},indent=2))
print('Built and hashed accessibility helper: '+str(output.stat().st_size)+' bytes')
