from __future__ import annotations
import argparse, os, re, shutil, time
from pathlib import Path

MASTER_RE = re.compile(r'(?im)^(?P<indent>\s*)(?P<fence>`{0,3}\s*)?(?:pythonw?(?:\.exe)?|py(?:\.exe)?(?:\s+-3(?:\.\d+)?)?)\s+(?P<script>Agent[\\/][\w.-]+\.py)\b')
PY_PROBE_RE = re.compile(r'(?i)\bwhere(?:\.exe)?\s+(?:pythonw?|py)(?:\.exe)?\b|shutil\.which\(\s*["\']python(?:w)?(?:\.exe)?["\']\s*\)')
BARE_PY_RE = re.compile(r'(?im)^\s*(?:call\s+|start\s+(?:"[^"]*"\s+)?)?(?:pythonw?(?:\.exe)?|py(?:\.exe)?(?:\s+-3(?:\.\d+)?)?)\s+')
ABS_USER_RE = re.compile(r'(?i)[A-Z]:\\Users\\[^\\\r\n"\']+(?:\\[^\r\n"\']*)?')

BAT_ENV_BLOCK = r'''rem PORTABLEAI_PORTABLE_PYTHON_v15_85_BEGIN
for %%# in ("%~dp0..") do set "_PAI_ROOT=%%~f#"
if exist "%_PAI_ROOT%\Runtime\BootstrapPython\python.exe" set "PATH=%_PAI_ROOT%\Runtime\BootstrapPython;%PATH%"
rem PORTABLEAI_PORTABLE_PYTHON_v15_85_END
'''

VBS_ENV_BLOCK = r'''Dim paiEnv, paiLaunchDir, paiRootDir, paiBootstrap
Set paiEnv = shell.Environment("PROCESS")
paiLaunchDir = fso.GetParentFolderName(WScript.ScriptFullName)
paiRootDir = fso.GetParentFolderName(paiLaunchDir)
paiBootstrap = fso.BuildPath(paiRootDir, "Runtime\BootstrapPython")
If fso.FileExists(fso.BuildPath(paiBootstrap, "python.exe")) Then paiEnv("PATH") = paiBootstrap & ";" & paiEnv("PATH")
'''


def backup(root: Path, bk: Path, p: Path) -> None:
    rel = p.relative_to(root)
    dst = bk / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(p, dst)


def write_if_changed(root: Path, bk: Path, p: Path, new: str, changes: list[str]) -> bool:
    old = p.read_text('utf-8', errors='replace')
    if new == old:
        return False
    backup(root, bk, p)
    p.write_text(new, 'utf-8', newline='')
    changes.append(str(p.relative_to(root)))
    return True


def patch_master(root: Path, bk: Path, changes: list[str]) -> None:
    for p in sorted(root.glob('PortableAI_Master_Instructions*.txt')) + sorted(root.glob('PortableAI_Master_Instructions*.md')):
        s = p.read_text('utf-8', errors='replace')
        def repl(m: re.Match[str]) -> str:
            return f"{m.group('indent')}{m.group('fence') or ''}.\\Tools\\portable_python.cmd {m.group('script')}"
        new = MASTER_RE.sub(repl, s)
        write_if_changed(root, bk, p, new, changes)


def patch_bat_launcher(root: Path, bk: Path, p: Path, changes: list[str]) -> None:
    s = p.read_text('utf-8', errors='replace')
    if 'PORTABLEAI_PORTABLE_PYTHON_v15_85_BEGIN' in s:
        return
    if not (PY_PROBE_RE.search(s) or BARE_PY_RE.search(s)):
        return
    lines = s.splitlines(True)
    idx = 1 if lines and lines[0].lstrip().lower().startswith('@echo off') else 0
    lines.insert(idx, BAT_ENV_BLOCK)
    write_if_changed(root, bk, p, ''.join(lines), changes)


def patch_vbs_launcher(root: Path, bk: Path, p: Path, changes: list[str]) -> None:
    s = p.read_text('utf-8', errors='replace')
    if 'paiBootstrap' in s or not PY_PROBE_RE.search(s):
        return
    # Safe injection only when the conventional FileSystemObject setup exists.
    m = re.search(r'(?im)^\s*Set\s+fso\s*=\s*CreateObject\("Scripting\.FileSystemObject"\)\s*$', s)
    if not m:
        return
    end = s.find('\n', m.end())
    if end < 0: end = m.end()
    else: end += 1
    new = s[:end] + VBS_ENV_BLOCK + s[end:]
    write_if_changed(root, bk, p, new, changes)


def patch_secure_ps1(root: Path, bk: Path, p: Path, changes: list[str], unresolved: list[str]) -> None:
    s = p.read_text('utf-8', errors='replace')
    root_s = str(root)
    if root_s.lower() not in s.lower():
        return
    out=[]; changed=False
    for line in s.splitlines(True):
        low=line.lower(); pos=low.find(root_s.lower())
        if pos < 0:
            out.append(line); continue
        # Replace only when the hard-coded root occurs inside a double-quoted PS string.
        before=line[:pos]
        if before.count('"') % 2 == 1:
            line=line[:pos] + '$(Split-Path -Parent $PSScriptRoot)' + line[pos+len(root_s):]
            changed=True
        else:
            unresolved.append(f'{p.relative_to(root)}: hard-coded root was not in a safe double-quoted context')
        out.append(line)
    if changed:
        write_if_changed(root,bk,p,''.join(out),changes)


def patch_ai_tools_ffmpeg(root: Path, bk: Path, changes: list[str]) -> None:
    p=root/'Agent'/'ai_tools.py'
    if not p.exists(): return
    s=p.read_text('utf-8',errors='replace'); new=s
    for tool in ('ffmpeg','ffprobe'):
        pat=re.compile(rf'def _find_{tool}\(\) -> str:\n.*?(?=\ndef |\Z)', re.S)
        m=pat.search(new)
        if not m or f'shutil.which("{tool}")' not in m.group(0):
            continue
        helper=(f'def _find_{tool}() -> str:\n'
                f'    cand = root_dir() / "Tools" / "ffmpeg" / "bin" / "{tool}.exe"\n'
                f'    if cand.exists():\n'
                f'        return str(cand)\n'
                f'    raise RuntimeError("PortableAI bundled {tool}.exe was not found at Tools/ffmpeg/bin/{tool}.exe")\n')
        new=new[:m.start()]+helper+new[m.end():]
    write_if_changed(root,bk,p,new,changes)


def patch_sfx_tools_candidate(root: Path, bk: Path, changes: list[str]) -> None:
    p=root/'Agent'/'sfx_bridge.py'
    if not p.exists(): return
    s=p.read_text('utf-8',errors='replace'); new=s
    for tool in ('ffmpeg','ffprobe'):
        marker=f'self.root / "Tools" / "ffmpeg" / "bin" / "{tool}.exe"'
        if marker not in new:
            pat=re.compile(rf'(def _{tool}\(self\) -> str:\s*\n\s*candidates\s*=\s*\[\s*\n)',re.M)
            new=pat.sub(lambda m:m.group(1)+f'            {marker},\n',new,count=1)
        # Once a bundled/local candidate list exists, remove host PATH fallback.
        pat2=re.compile(rf'\n(?P<i>\s*)exe = shutil\.which\("{tool}"\)\s*\n(?P=i)if exe:\s*\n(?P=i)    return exe')
        new=pat2.sub('',new,count=1)
        pat3=re.compile(rf'\n(?P<i>\s*)return shutil\.which\("{tool}"\)')
        new=pat3.sub(lambda m:'\n'+m.group('i')+f'raise RuntimeError("PortableAI local {tool}.exe was not found")',new,count=1)
    write_if_changed(root,bk,p,new,changes)


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',required=True)
    ns=ap.parse_args(); root=Path(ns.root).resolve()
    stamp=time.strftime('%Y%m%d_%H%M%S')
    bk=root/'Backups'/f'Portability_v15.85_before_apply_{stamp}'
    changes=[]; unresolved=[]

    # Master instructions: all Agent Python commands go through the local orchestration wrapper.
    patch_master(root,bk,changes)

    # Top-level orchestration launchers only. Never inject BootstrapPython into component ML launchers.
    launchers=root/'Launchers'
    if launchers.exists():
        for p in sorted(launchers.iterdir()):
            if not p.is_file(): continue
            low=p.name.lower()
            if low.startswith('test_'): continue
            if p.suffix.lower() in {'.bat','.cmd'}: patch_bat_launcher(root,bk,p,changes)
            elif p.suffix.lower()=='.vbs': patch_vbs_launcher(root,bk,p,changes)
            elif p.suffix.lower()=='.ps1' and 'secure' in low: patch_secure_ps1(root,bk,p,changes,unresolved)

    # Root VBS launchers can also be entry points.
    for p in root.glob('*.vbs'):
        patch_vbs_launcher(root,bk,p,changes)

    patch_ai_tools_ffmpeg(root,bk,changes)
    patch_sfx_tools_candidate(root,bk,changes)

    print('PortableAI portability fixes v15.85')
    print('='*76)
    if changes:
        print('Backed up and changed:')
        for x in changes: print('  ',x)
        print('Backup:',bk)
    else:
        print('No eligible runtime-sensitive files needed changes.')
    if unresolved:
        print('\nUNRESOLVED (left unchanged for safety):')
        for x in unresolved: print('  ',x)
    print('\nNo component ML Python environment was modified.')
    return 0

if __name__=='__main__': raise SystemExit(main())
