"""Build the Windows installer UI with its current portable install engine.

The input bootstrap is a pinned public Python archive. Application payloads and
release inventories remain external. No live application data is copied.
"""
import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile
import shutil

HERE = Path(__file__).resolve().parent

def build(bootstrap, output):
    bootstrap = Path(bootstrap).resolve()
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    if bootstrap.stat().st_size != 11439094 or hashlib.sha256(bootstrap.read_bytes()).hexdigest() != '97dae5274cc54867065e8d5a3226e48c35017ed332a0fdb0e27d5b5821961297':
        raise RuntimeError('Installer bootstrap checksum mismatch')
    output.parent.mkdir(parents=True, exist_ok=True)
    compiler = Path('C:/Windows/Microsoft.NET/Framework64/v4.0.30319/csc.exe')
    subprocess.run([str(compiler), '/nologo', '/target:winexe', '/platform:x64', f'/out:{output}',
                    '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll',
                    '/reference:System.Web.Extensions.dll', '/reference:System.IO.Compression.dll',
                    '/reference:System.IO.Compression.FileSystem.dll',
                    f'/resource:{bootstrap},python-bootstrap.zip',
                    f'/resource:{HERE / "installer_core.py"},installer_core.py',
                    f'/resource:{HERE / "engine_cli.py"},engine_cli.py',
                    f'/resource:{HERE / "installer_storage.py"},installer_storage.py',
                    f'/resource:{HERE / "portable_update.py"},portable_update.py',
                    f'/resource:{HERE / "suite_installer.py"},suite_installer.py',
                    f'/resource:{HERE / "abliterator_installer_core.py"},abliterator_installer_core.py', str(HERE / 'Installer.cs')],
                   cwd=HERE, check=True)
    return hashlib.sha256(output.read_bytes()).hexdigest()

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--bootstrap',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(build(args.bootstrap,args.output))
