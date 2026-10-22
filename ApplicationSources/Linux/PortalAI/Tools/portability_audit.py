from __future__ import annotations
import argparse, json, os, re, time
from pathlib import Path

# v15.85 audits code that can actually participate in PortableAI startup,
# orchestration, or tool execution. It deliberately does NOT crawl vendored
# applications, model repositories, package caches, tests, docs, or tokenizers.
SCRIPT_EXT={'.py','.ps1','.bat','.cmd','.vbs'}
CONFIG_EXT={'.json','.yaml','.yml','.toml','.ini','.cfg'}
MASTER_GLOBS=('PortableAI_Master_Instructions*.txt','PortableAI_Master_Instructions*.md')
CORE_DIRS=('Agent','ControlCenter','Tools','Launchers')
SHALLOW_COMPONENT_DIRS=('Services','SpeechToText','Voice','Video','Music','Generative')

SKIP_ANYWHERE={
    '.git','__pycache__','.runtime','cache','caches','uv-cache','uv_cache','outputs','output',
    'temp','tmp','node_modules','backups','models','model','checkpoints','weights','downloads',
    '.venv','venv','site-packages','python_embeded','python-embeded','python-base','python',
    'huggingface','hf_cache','.cache','repositories','repo-cache','portablgit','portablegit',
    'tests','test','tests-unit','.github','docs','doc','examples','example','benchmarks','benchmark',
    'updatepayload','dist','build'
}

# Runtime-sensitive filenames under otherwise vendored component trees.
SHALLOW_NAME_HINTS=(
    'start','stop','launch','launcher','run','install','setup','bootstrap','config','service','server',
    'bridge','controller','manager','portable','runtime'
)

RX_ABS_USER=re.compile(r'(?i)[A-Z]:\\Users\\[^\\\r\n"\']+')
RX_APPDATA=re.compile(r'(?i)(%APPDATA%|%LOCALAPPDATA%|\\AppData\\|\$env:(?:LOCAL)?APPDATA)')
RX_FFMPEG_PROBE=re.compile(r'(?i)(shutil\.which\(\s*["\']ffmpeg(?:\.exe)?["\']|\bwhere(?:\.exe)?\s+ffmpeg(?:\.exe)?)')
RX_FFPROBE_PROBE=re.compile(r'(?i)(shutil\.which\(\s*["\']ffprobe(?:\.exe)?["\']|\bwhere(?:\.exe)?\s+ffprobe(?:\.exe)?)')
RX_PY_PROBE=re.compile(r'(?i)(shutil\.which\(\s*["\']python(?:w)?(?:\.exe)?["\']|\bwhere(?:\.exe)?\s+(?:pythonw?|py)(?:\.exe)?)')
RX_CUDA_TOOLKIT=re.compile(r'(?i)(CUDA_PATH|\\CUDA\\v\d|\bnvcc(?:\.exe)?\b)')
RX_GIT_CMD=re.compile(r'(?im)(?:^|[;&|]\s*|["\'])(git(?:\.exe)?)(?=\s+(?:clone|pull|fetch|checkout|submodule)\b)')
RX_NODE_CMD=re.compile(r'(?im)(?:^|[;&|]\s*|["\'])(node(?:\.exe)?|npm(?:\.cmd)?|npx(?:\.cmd)?)(?=\s|["\'])')

# Shell/VBS/PowerShell bare Python execution. Avoid matching variable names such as
# "py = FindPython(...)" or prose/tokenizer text.
RX_SHELL_PY_CMD=re.compile(
    r'(?im)^\s*(?:call\s+|start\s+(?:"[^"]*"\s+)?|cmd(?:\.exe)?\s+/[cdk]+\s+)?'
    r'(?P<cmd>pythonw?(?:\.exe)?|py(?:\.exe)?(?:\s+-3(?:\.\d+)?)?)\s+(?=[-\w"%.$])'
)
RX_SUBPROCESS_PY=re.compile(
    r'(?is)(?:subprocess\.(?:run|Popen|call|check_call|check_output)|os\.system)\s*\([^\n]{0,240}?'
    r'["\'](?:pythonw?(?:\.exe)?|py(?:\.exe)?)["\']'
)
RX_MASTER_PY=re.compile(r'(?im)^\s*(?:`{0,3})\s*(pythonw?(?:\.exe)?|py(?:\.exe)?(?:\s+-3(?:\.\d+)?)?)\s+Agent[\\/]ai_tools\.py\b')

def is_dev_or_irrelevant(rel: str) -> bool:
    low=rel.replace('\\','/').lower()
    name=low.rsplit('/',1)[-1]
    if name.startswith('test_') or '/legacydiagnosis/' in low:
        return True
    # This PortableAI build explicitly assumes Windows + NVIDIA, so ROCm launchers
    # are not part of the runnable host surface on the target class.
    if 'rocm' in name:
        return True
    return False


def is_skipped_part(p:Path)->bool:
    return any(part.lower() in SKIP_ANYWHERE for part in p.parts)


def add_file(out:list[Path], seen:set[str], p:Path):
    try:
        if not p.is_file() or p.stat().st_size > 2_000_000:
            return
        key=str(p.resolve()).lower()
    except Exception:
        return
    if key not in seen:
        seen.add(key); out.append(p)


def collect_candidates(root:Path, max_seconds:float):
    started=time.monotonic(); out=[]; seen=set(); incomplete=False

    # 1) Root launch/config scripts only. No recursive root crawl.
    try:
        for p in root.iterdir():
            if p.is_file() and p.suffix.lower() in (SCRIPT_EXT|CONFIG_EXT):
                add_file(out,seen,p)
        for pat in MASTER_GLOBS:
            for p in root.glob(pat): add_file(out,seen,p)
    except Exception:
        pass

    # 2) Our own orchestration directories may be recursive, but prune aggressively.
    for dirname in CORE_DIRS:
        base=root/dirname
        if not base.exists(): continue
        for cur,dirs,files in os.walk(base,topdown=True):
            curp=Path(cur)
            dirs[:] = [d for d in dirs if d.lower() not in SKIP_ANYWHERE]
            if curp == root/'Tools':
                dirs[:] = [d for d in dirs if d.lower() != 'kicad' and not d.lower().startswith('kicad.staging-')]
            if time.monotonic()-started > max_seconds:
                incomplete=True; break
            for name in files:
                p=curp/name
                ext=p.suffix.lower()
                if ext in SCRIPT_EXT or ext in CONFIG_EXT:
                    add_file(out,seen,p)
                elif dirname=='Agent' and name.lower() in {'reference.md'}:
                    add_file(out,seen,p)
        if incomplete: break

    # 3) Component trees are mostly third-party payloads. Inspect only the component
    #    root and one directory below it, and only launcher/runtime-looking files.
    if not incomplete:
        for dirname in SHALLOW_COMPONENT_DIRS:
            base=root/dirname
            if not base.exists(): continue
            try:
                for p in base.iterdir():
                    if time.monotonic()-started > max_seconds:
                        incomplete=True; break
                    if p.is_file():
                        low=p.name.lower()
                        if p.suffix.lower() in SCRIPT_EXT and any(h in low for h in SHALLOW_NAME_HINTS):
                            add_file(out,seen,p)
                    elif p.is_dir() and p.name.lower() not in SKIP_ANYWHERE:
                        # one level only; never recurse into ComfyUI/OpenWebUI/vendor packages
                        try:
                            for q in p.iterdir():
                                if not q.is_file(): continue
                                low=q.name.lower()
                                if q.suffix.lower() in SCRIPT_EXT and any(h in low for h in SHALLOW_NAME_HINTS):
                                    add_file(out,seen,q)
                        except Exception:
                            pass
            except Exception:
                pass
            if incomplete: break
    return out,incomplete,time.monotonic()-started


def line_no(s:str,pos:int)->int:
    return s.count('\n',0,pos)+1


def hit(hits,kind,severity,rel,s,m):
    hits.append({'kind':kind,'severity':severity,'file':rel,'line':line_no(s,m.start()),'match':m.group(0)[:180]})


def scan_file(root:Path,p:Path,local_ffmpeg:bool):
    hits=[]
    try:
        rel=p.relative_to(root).as_posix(); s=p.read_text('utf-8',errors='ignore')
    except Exception:
        return hits
    ext=p.suffix.lower(); name=p.name.lower()
    is_master=name.startswith('portableai_master_instructions')
    dev_only=is_dev_or_irrelevant(rel)
    # v15.85 fix marker means host-style python names resolve process-locally to BootstrapPython.
    local_py_env=('PORTABLEAI_PORTABLE_PYTHON_v15_85_BEGIN' in s or 'paiBootstrap' in s)
    # Do not let the audit implementation's own detector regex/constants flag themselves.
    self_audit=(rel.lower()=='tools/portability_audit.py')

    def sev(default='BLOCKER'):
        return 'ADVISORY' if (dev_only or local_py_env) else default

    # Hard-coded user profile paths are genuine portability concerns in executable/config code.
    for m in list(RX_ABS_USER.finditer(s))[:5]: hit(hits,'absolute_user_path',sev(),rel,s,m)
    if not self_audit:
        for m in list(RX_APPDATA.finditer(s))[:5]: hit(hits,'appdata_reference','ADVISORY',rel,s,m)

    # Interpreter discovery/invocation is meaningful only in executable scripts or master instructions.
    if ext in SCRIPT_EXT:
        for m in list(RX_PY_PROBE.finditer(s))[:5]: hit(hits,'host_python_probe',sev(),rel,s,m)
        if ext=='.py':
            for m in list(RX_SUBPROCESS_PY.finditer(s))[:5]: hit(hits,'bare_python_exec',sev(),rel,s,m)
        else:
            for m in list(RX_SHELL_PY_CMD.finditer(s))[:5]: hit(hits,'bare_python_exec',sev(),rel,s,m)
    if is_master:
        for m in list(RX_MASTER_PY.finditer(s))[:20]: hit(hits,'master_instruction_bare_python','BLOCKER',rel,s,m)

    # PATH ffmpeg/ffprobe lookups are harmless fallbacks when the bundled binaries exist.
    ffsev='ADVISORY' if local_ffmpeg else 'BLOCKER'
    for m in list(RX_FFMPEG_PROBE.finditer(s))[:5]: hit(hits,'host_ffmpeg_probe',ffsev,rel,s,m)
    for m in list(RX_FFPROBE_PROBE.finditer(s))[:5]: hit(hits,'host_ffprobe_probe',ffsev,rel,s,m)

    # Toolkit/runtime command checks are command-context only, not detector definitions in this file.
    if not self_audit:
        for m in list(RX_GIT_CMD.finditer(s))[:5]: hit(hits,'git_runtime',sev(),rel,s,m)
        for m in list(RX_NODE_CMD.finditer(s))[:5]: hit(hits,'node_runtime',sev(),rel,s,m)
        for m in list(RX_CUDA_TOOLKIT.finditer(s))[:5]: hit(hits,'cuda_toolkit',sev(),rel,s,m)
    return hits

def anyp(root,rels):
    for r in rels:
        if (root/r).exists(): return r


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--root',required=True)
    ap.add_argument('--json',action='store_true')
    ap.add_argument('--max-seconds',type=float,default=20.0)
    ns=ap.parse_args(); root=Path(ns.root).resolve(); started=time.monotonic()
    owned={
      'bootstrap_python_3_12':anyp(root,['Runtime/BootstrapPython/python.exe']),
      'ffmpeg':anyp(root,['Tools/ffmpeg/bin/ffmpeg.exe','Runtime/MMAudioFFmpeg/bin/ffmpeg.exe']),
      'comfyui':anyp(root,['Generative/ComfyUI_windows_portable']),
      'runtime_lock_report':anyp(root,['Agent/.runtime/component_runtime_locks.json']),
    }
    print('[audit] Targeted startup/orchestration audit started. Vendored apps, caches, models, docs and tests are excluded.',flush=True)
    candidates,incomplete,collect_elapsed=collect_candidates(root,ns.max_seconds)
    print(f'[audit] {len(candidates)} runtime-sensitive files selected in {collect_elapsed:.2f}s.',flush=True)
    hits=[]; scanned=0
    local_ffmpeg=bool(owned['ffmpeg'])
    for p in candidates:
        if time.monotonic()-started > ns.max_seconds:
            incomplete=True; print(f'[audit] Time budget reached after {ns.max_seconds:.0f}s; writing partial REVIEW report.',flush=True); break
        hits.extend(scan_file(root,p,local_ffmpeg)); scanned+=1
    elapsed=round(time.monotonic()-started,2)
    blockers=[h for h in hits if h['severity']=='BLOCKER']
    advisories=[h for h in hits if h['severity']=='ADVISORY']
    status='PASS' if owned['bootstrap_python_3_12'] and owned['runtime_lock_report'] and not blockers and not incomplete else 'REVIEW'
    result={
      'schema':4,
      'root':str(root),
      'policy':'Windows x64 + NVIDIA driver are assumed; component runtimes are frozen, not unified.',
      'scan_mode':'targeted-runtime-sensitive-files',
      'scan_stats':{'elapsed_seconds':elapsed,'candidate_files':len(candidates),'files_scanned':scanned,'incomplete':incomplete},
      'portable_owned':owned,
      'blocker_count':len(blockers),'advisory_count':len(advisories),
      'blockers':blockers,'advisories':advisories,'hits':hits,'status':status,
    }
    out=root/'Agent'/'.runtime'/'portability_audit.json'; out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    if ns.json:
        print(json.dumps(result,indent=2)); return 0 if status=='PASS' else 2
    print('PortableAI portability audit v15.85'); print('='*76)
    for k,v in owned.items(): print(f'{k:24} {"LOCAL" if v else "MISSING":8} {v or ""}')
    print(f'\nScanned {scanned}/{len(candidates)} runtime-sensitive files in {elapsed:.2f}s; '+('PARTIAL' if incomplete else 'complete'))
    print(f'BLOCKERS: {len(blockers)} | ADVISORIES: {len(advisories)}')
    if blockers:
        print('\nBLOCKERS (can create a host dependency):')
        for h in blockers[:80]: print(f'  {h["kind"]:30} {h["file"]}:{h["line"]}  {h["match"]}')
    if advisories:
        print('\nADVISORIES (fallback/reference; bundled equivalent exists or host state is optional):')
        for h in advisories[:60]: print(f'  {h["kind"]:30} {h["file"]}:{h["line"]}  {h["match"]}')
    print('\nReport:',out)
    return 0 if status=='PASS' else 2

if __name__=='__main__': raise SystemExit(main())
