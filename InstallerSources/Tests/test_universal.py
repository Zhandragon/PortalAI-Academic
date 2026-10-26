from pathlib import Path
import copy,hashlib,json,os,shutil,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]/'Universal'
BASH=r'C:\Program Files\Git\bin\bash.exe'

class UniversalTests(unittest.TestCase):
    def test_bash_unconfigured_url_reads_user_input_not_manifest(self):
        with tempfile.TemporaryDirectory(prefix='PortalAI-universal-prompt-') as tmp:
            root=Path(tmp);(root/'Packages').mkdir();(root/'bin').mkdir()
            rows=[]
            for platform in ('Windows','Linux','Mac'):
                data=(platform+' fixture').encode();name=platform+'.pkg'
                (root/'Packages'/name).write_bytes(data)
                rows.append(dict(platform=platform,file=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),url='UNCONFIGURED'))
            (root/'fixture').write_bytes((root/'Packages/Windows.pkg').read_bytes());(root/'Packages/Windows.pkg').unlink()
            (root/'assets.tsv').write_text(''.join('\t'.join(str(r[k]) for k in ('platform','file','bytes','sha256','url'))+'\n' for r in rows),newline='\n')
            shutil.copy2(ROOT/'prepare-universal.sh',root/'prepare-universal.sh')
            (root/'bin/curl').write_text('#!/bin/bash\nwhile [ "$#" -gt 0 ]; do if [ "$1" = --output ]; then dest="$2"; shift 2; else url="$1"; shift; fi; done\n[ "$url" = https://github.com/Example/Full/releases/download/v1/Windows.pkg ] || exit 17\ncp -- "$UNIVERSAL_TEST_FIXTURE" "$dest"\n',newline='\n')
            script='cd "'+root.as_posix()+'"; export PATH="$PWD/bin:$PATH"; [ "$(command -v curl)" = "$PWD/bin/curl" ] || exit 19; exec bash prepare-universal.sh --prepare-only'
            result=subprocess.run([BASH,'-c',script],input=b'https://github.com/Example/Full/releases/download/v1\n',env={**os.environ,'UNIVERSAL_TEST_FIXTURE':(root/'fixture').as_posix()},capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual((root/'Packages/Windows.pkg').read_bytes(),(root/'fixture').read_bytes())
    def check(self,shell,case):
        with tempfile.TemporaryDirectory(prefix='PortalAI-universal-test-') as tmp:
            root=Path(tmp);(root/'Packages').mkdir()
            rows=[]
            for platform in ('Windows','Linux','Mac'):
                data=(platform+' fixture').encode();name=platform+'.pkg'
                (root/'Packages'/name).write_bytes(data)
                rows.append(dict(platform=platform,file=name,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),url=''))
            if case=='corrupt':(root/'Packages/Windows.pkg').write_bytes(b'corrupted')
            if case=='missing':(root/'Packages/Mac.pkg').unlink()
            if case=='duplicate':rows[2]=copy.deepcopy(rows[0])
            if case=='escape':rows[0]['file']='../escape'
            if case=='bad_hash':rows[0]['sha256']='bad'
            if case=='too_few':rows.pop()
            (root/'universal.json').write_text(json.dumps(dict(schema=1,version='fixture',assets=rows)))
            (root/'assets.tsv').write_text(''.join('\t'.join(str(r[k] or 'UNCONFIGURED') for k in ('platform','file','bytes','sha256','url'))+'\n' for r in rows))
            name='prepare-universal.'+('sh' if shell=='bash' else 'ps1');shutil.copy2(ROOT/name,root/name)
            cmd=[BASH,str(root/name),'--verify-only'] if shell=='bash' else ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/name),'-VerifyOnly']
            result=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode==0,case=='valid',result.stdout+result.stderr)
            self.assertFalse(list(root.rglob('*.part-*')))

for shell in ('bash','powershell'):
    for case in ('valid','corrupt','missing','duplicate','escape','bad_hash','too_few'):
        setattr(UniversalTests,'test_'+shell+'_'+case,lambda self,shell=shell,case=case:self.check(shell,case))
class LaunchAndPrivateTests(unittest.TestCase):
    def test_windows_launch_uses_matching_edition_filename(self):
        import zipfile
        edition=json.loads((ROOT/'universal.json').read_text())['edition']
        launcher='PortalAI-Academic-Install.exe' if edition=='Academic' else 'PortalAI-Install.exe'
        with tempfile.TemporaryDirectory(prefix='PortalAI-universal-launch-') as tmp:
            folder=Path(tmp);(folder/'Packages').mkdir()
            with zipfile.ZipFile(folder/'Packages/Windows.zip','w') as z:z.writestr(launcher,b'fixture; must never execute')
            rows=[]
            for platform in ('Windows','Linux','Mac'):
                path=folder/'Packages'/('Windows.zip' if platform=='Windows' else platform+'.pkg')
                if platform!='Windows':path.write_bytes(platform.encode())
                rows.append(dict(platform=platform,file=path.name,bytes=path.stat().st_size,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),url=''))
            (folder/'universal.json').write_text(json.dumps(dict(schema=1,edition=edition,version='fixture',assets=rows)))
            shutil.copyfile(ROOT/'prepare-universal.ps1',folder/'prepare-universal.ps1')
            harness="function Read-Host { 'y' }; function Start-Process { param($FilePath,$WorkingDirectory); if (-not (Test-Path -LiteralPath $FilePath) -or [IO.Path]::GetFileName($FilePath) -ne '"+launcher+"') { throw 'Wrong edition launcher' }; Write-Output 'LAUNCH_VALIDATED' }; & '"+str(folder/'prepare-universal.ps1')+"'"
            p=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-Command',harness],capture_output=True,text=True,timeout=30)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertIn('LAUNCH_VALIDATED',p.stdout)

    def test_private_missing_download_gives_actionable_instructions(self):
        manifest=json.loads((ROOT/'universal.json').read_text())
        if not manifest.get('private_release'):self.skipTest('Public release downloads automatically')
        for shell in ('ps1','sh'):
            with tempfile.TemporaryDirectory(prefix='PortalAI-private-download-') as tmp:
                folder=Path(tmp)
                for name in ('universal.json','assets.tsv','prepare-universal.'+shell):shutil.copyfile(ROOT/name,folder/name)
                cmd=([BASH,str(folder/'prepare-universal.sh'),'--prepare-only'] if shell=='sh' else ['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(folder/'prepare-universal.ps1'),'-PrepareOnly'])
                p=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
                self.assertNotEqual(p.returncode,0);self.assertIn('signed-in GitHub browser',p.stdout+p.stderr)
                self.assertFalse(list(folder.rglob('*.part-*')))

if __name__=='__main__':unittest.main(verbosity=2)

