"""Import a resolved AMD stack into its own portable Python 3.12 package layer.

The resolution report pins artifact SHA-256; upstream AMD's index currently
does not publish separate archive hashes. Verify bytes and wheel RECORD entries
before pip installs locally. Never replace an existing package destination.
"""
import argparse
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"Agent"))
from runtime_policy import GIB, atomic_json, portable_env, portable_path, require_space


def digest(path):
    with path.open("rb") as f:return hashlib.file_digest(f,"sha256").hexdigest()


def wheel_check(path, allow_hex_record=False):
    with zipfile.ZipFile(path) as z:
        entries=z.infolist()
        require_space(ROOT, sum(x.file_size for x in entries))
        for member in entries:
            portable_path(ROOT/"Cache/imports/wheel-validation",member.filename)
            if member.file_size > 4*GIB:raise ValueError("Unexpected giant wheel member")
        # Vendored packages (notably setuptools) contain their own nested
        # RECORDs. The outer wheel RECORD covers those files as data too.
        records=[n for n in z.namelist() if n.endswith(".dist-info/RECORD") and n.count("/")==1]
        if len(records)!=1:raise ValueError("Missing/ambiguous wheel RECORD: "+path.name)
        for name,checksum,size in csv.reader(io.StringIO(z.read(records[0]).decode())):
            if not checksum:continue
            algorithm,value=checksum.split("=",1)
            if algorithm!="sha256":raise ValueError("Unexpected RECORD hash algorithm")
            with z.open(name) as f:actual=hashlib.file_digest(f,"sha256").digest()
            matches=base64.urlsafe_b64encode(actual).rstrip(b"=").decode()==value
            if allow_hex_record and actual.hex()==value:matches=True
            if not matches or z.getinfo(name).file_size!=int(size):
                raise RuntimeError("Wheel member verification failed: "+name)
        return sum(x.file_size for x in entries)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--install",action="store_true");args=parser.parse_args()
    report=json.loads((ROOT/"Maintenance/Imports/amd-runtime-resolution.json").read_text(encoding="utf-8"))
    items=report["install"]
    assert any(r["metadata"]["name"]=="torch" and r["metadata"]["version"]=="2.14.0+rocm10.1.0" for r in items)
    dest=ROOT/"Runtime/AMDPython/packages"
    if dest.exists():raise RuntimeError("AMD destination exists; verify it instead of overwriting")
    require_space(ROOT,30*GIB)
    wheelhouse=ROOT/"Cache/AMD-wheelhouse";wheelhouse.mkdir(parents=True,exist_ok=True)
    assets=[];expanded=0;source=None
    for item in items:
        info=item["download_info"];url=info["url"];sha=info["archive_info"]["hashes"]["sha256"]
        parsed=urllib.parse.urlparse(url);filename=urllib.parse.unquote(Path(parsed.path).name)
        if filename.endswith(".tar.gz"):
            source=ROOT/"Cache/imports/rocm-10.1.0.tar.gz"
            if item["metadata"]["name"]!="rocm" or source.stat().st_size!=27536 or digest(source)!=sha:
                raise RuntimeError("Unreviewed source package")
            continue
        if parsed.scheme!="https" or parsed.hostname not in ("stable.repo.amd.com","files.pythonhosted.org") or not filename.endswith(".whl"):
            raise ValueError("Unexpected artifact URL: "+url)
        target=wheelhouse/filename
        headers=urllib.request.urlopen(urllib.request.Request(url,method="HEAD"),timeout=45).headers
        size=int(headers["Content-Length"])
        require_space(ROOT,size)
        if not target.exists():
            key=hashlib.sha224(url.encode()).hexdigest()
            cached=ROOT/"Cache/pip/http-v2"/key[0]/key[1]/key[2]/key[3]/key[4]/(key+".body")
            if cached.is_file() and cached.stat().st_size==size and digest(cached)==sha:
                os.link(cached,target)
            else:
                part=target.with_suffix(".part")
                with urllib.request.urlopen(url,timeout=45) as src, part.open("wb") as out:
                    total=0
                    for block in iter(lambda:src.read(4*1024**2),b""):
                        total+=len(block)
                        if total>size:raise RuntimeError("Download exceeded declared byte size")
                        require_space(ROOT,len(block));out.write(block)
                if part.stat().st_size!=size or digest(part)!=sha:raise RuntimeError("AMD artifact hash/size mismatch")
                part.rename(target)
        if target.stat().st_size!=size or digest(target)!=sha:raise RuntimeError("Cached AMD artifact differs from resolution")
        expanded+=wheel_check(target)
        assets.append({"name":item["metadata"]["name"],"version":item["metadata"]["version"],"url":url,"bytes":size,"sha256":sha,"wheel":target.relative_to(ROOT).as_posix()})
        print("Verified "+filename,flush=True)
    require_space(ROOT,expanded*2+GIB)
    env=portable_env(ROOT);env.update(ROCM_SDK_TARGET_FAMILY="gfx1150",PYTHONUTF8="1",PYTHONIOENCODING="utf-8")
    if not source:raise RuntimeError("Missing ROCm metadata source")
    subprocess.run([sys.executable,"-B","-m","pip","wheel","--no-deps","--no-index","--find-links",str(wheelhouse),"--wheel-dir",str(wheelhouse),str(source)],env=env,cwd=ROOT,check=True)
    local=wheelhouse/"rocm-10.1.0-py3-none-any.whl";wheel_check(local)
    assets.append({"name":"rocm","version":"10.1.0","source_sha256":digest(source),"bytes":local.stat().st_size,"sha256":digest(local),"wheel":local.relative_to(ROOT).as_posix()})
    manifest={"hash_provenance":"Pinned from HTTPS resolution; checked again plus individual wheel RECORD hashes. AMD index has no separate publisher archive hashes.",
              "assets":assets,"expanded_bytes":expanded,"status":"verified-staged"}
    atomic_json(ROOT/"Maintenance/Imports/amd-runtime-lock.json",manifest)
    if not args.install:return
    stage=ROOT/"Runtime/AMDPython/packages-stage"
    if stage.exists():raise RuntimeError("Review previous AMD stage before retrying")
    requirements=wheelhouse/"install-locked.txt"
    requirements.write_text("\n".join((ROOT/a["wheel"]).as_uri()+" --hash=sha256:"+a["sha256"] for a in assets),encoding="utf-8")
    subprocess.run([sys.executable,"-B","-m","pip","install","--no-index","--no-deps","--require-hashes","--no-compile","--target",str(stage),"-r",str(requirements)],cwd=ROOT,env=env,check=True)
    from portable_permissions import grant_runtime_read_execute
    grant_runtime_read_execute(ROOT, stage)
    os.replace(stage,dest)
    manifest.update(status="installed-unvalidated-on-Radeon",installed_path=dest.relative_to(ROOT).as_posix())
    atomic_json(ROOT/"Maintenance/Imports/amd-runtime-lock.json",manifest)
    print(json.dumps({"status":manifest["status"],"assets":len(assets),"expanded_bytes":expanded}))


if __name__=="__main__":main()
