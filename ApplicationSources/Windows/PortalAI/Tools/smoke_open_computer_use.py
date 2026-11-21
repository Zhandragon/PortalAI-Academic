"""UIA-only test against a disposable nonactivating window; no physical input."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'Agent'),str(ROOT/'ControlCenter'),str(ROOT/'Tools')]

FIXTURE=r'''
param([string]$Receipt)
Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase
[xml]$xaml=@"
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation" xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml" Title="PortalAI synthetic accessibility fixture" ShowActivated="False" ShowInTaskbar="False" WindowStyle="ToolWindow" Left="20" Top="20" Width="440" Height="220">
<StackPanel Margin="20"><TextBox x:Name="FixtureInput" AutomationProperties.Name="Fixture name"/><Button x:Name="FixtureButton" Content="Invoke fixture" Margin="0,15,0,15"/><TextBlock x:Name="FixtureResult" Text="Not invoked"/></StackPanel>
</Window>
"@
$reader=New-Object System.Xml.XmlNodeReader $xaml
$form=[Windows.Markup.XamlReader]::Load($reader)
$inputBox=$form.FindName('FixtureInput');$button=$form.FindName('FixtureButton');$resultLabel=$form.FindName('FixtureResult')
$button.Add_Click({$resultLabel.Text='Verified '+$inputBox.Text})
$form.Show()
$helper=New-Object Windows.Interop.WindowInteropHelper $form
[System.IO.File]::WriteAllText($Receipt,[string]$helper.Handle.ToInt64())
[Windows.Threading.Dispatcher]::Run()
'''


def main():
    from validation_artifacts import ValidationArtifacts
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--artifacts-dir',required=True);args=parser.parse_args()
    artifacts=ValidationArtifacts(ROOT,Path(args.artifacts_dir));base=artifacts.path('ocu-fixture');base.mkdir(exist_ok=True)
    script=base/'fixture.ps1';script.write_text(FIXTURE,encoding='utf-8');receipt=base/'window.txt';receipt.unlink(missing_ok=True)
    user=ctypes.WinDLL('user32');user.GetForegroundWindow.restype=ctypes.c_void_p
    foreground=user.GetForegroundWindow()
    from tool_process import ToolProcess
    powershell=Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    env=dict(os.environ,TEMP=str(base),TMP=str(base))
    owner=ToolProcess(ROOT,[str(powershell),'-NoProfile','-NonInteractive','-STA','-ExecutionPolicy','Bypass','-File',str(script),str(receipt)],cwd=base,env=env,check=lambda:None,monitor=False)
    p=owner.start()
    try:
        deadline=time.monotonic()+15
        while not receipt.exists():
            if p.poll() is not None:raise RuntimeError(p.communicate()[1])
            if time.monotonic()>deadline:raise TimeoutError('Nonactivating fixture did not start')
            time.sleep(.05)
        assert user.GetForegroundWindow()==foreground,'Fixture unexpectedly changed foreground'
        hwnd=int(receipt.read_text())
        fixture_root=base/'root';layer=fixture_root/'Runtime/ComputerUse/windows-x64';layer.mkdir(parents=True,exist_ok=True)
        for name in ('runtime.ps1','manifest.json','LICENSE'):
            shutil.copy2(ROOT/'Runtime/ComputerUse/windows-x64'/name,layer/name)
        from desktop_control import Desktop
        row=Desktop(fixture_root,None).info(hwnd)
        from open_computer_use import call
        def check():
            assert user.GetForegroundWindow()==foreground,'Foreground changed; stop this background fixture'
            assert p.poll() is None,'Fixture ended'
        with patch('platform_runtime.python_path',return_value=Path(sys.executable)):
            state=call(fixture_root,row,check)['snapshot']
            (base/'state.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
            entry=next(e for e in state['elements'] if e.get('name')=='Fixture name')
            state=call(fixture_root,row,check,'set_value',state,str(entry['index']),'background test')['snapshot']
            button=next(e for e in state['elements'] if e.get('name')=='Invoke fixture')
            state=call(fixture_root,row,check,'click',state,str(button['index']))['snapshot']
            assert 'Verified background test' in json.dumps(state),state
            check()
            try:call(fixture_root,{**row,'created':row['created']+1},check)
            except RuntimeError as exc:assert 'identity changed' in str(exc),exc
            else:raise AssertionError('Changed process identity was accepted')
        report={'ok':True,'backend':'open-computer-use 1.1.5','text_state':True,'set_value':True,'invoke':True,'identity_rejected':True,'foreground_unchanged':True,'physical_input':False,'synthetic':True}
        (base/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report))
    finally:
        owner.close();p.communicate(timeout=5)


if __name__=='__main__':main()
