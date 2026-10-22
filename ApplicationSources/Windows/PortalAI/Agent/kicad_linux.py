"""Relocatable Linux KiCad CLI with isolated native libraries and private state."""
import os
from pathlib import Path
import sys
from xml.sax.saxutils import escape

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
from profile_paths import private_path
from runtime_policy import portable_env


def command_environment(root=ROOT):
    root=Path(root).resolve()
    # Resolve account state before creating any vendor configuration or cache.
    state=private_path(root,'Data/Science/KiCad')
    payload=root/'Runtime/LinuxSystem/kicad'
    lib=payload/'usr/lib'
    loader=lib/'kicad/ld-linux-x86-64.so.2'
    executable=payload/'usr/bin/kicad-cli'
    for file in (loader,executable,lib/'kicad/_eeschema.kiface',lib/'kicad/_pcbnew.kiface'):
        if not file.is_file():raise RuntimeError('Portable Linux KiCad payload is incomplete: '+str(file))
    env=portable_env(root)
    for key in ('LD_LIBRARY_PATH','LD_PRELOAD','LD_AUDIT','KICAD_RUN_FROM_BUILD_DIR'):
        env.pop(key,None)
    for key,relative in {'HOME':'home','XDG_CONFIG_HOME':'config','XDG_CACHE_HOME':'cache',
                         'XDG_DATA_HOME':'data','KICAD_CONFIG_HOME':'config/kicad',
                         'KICAD_CACHE_HOME':'cache','KICAD_DOCUMENTS_HOME':'documents',
                         'TEMP':'tmp','TMP':'tmp','TMPDIR':'tmp'}.items():
        path=state/relative;path.mkdir(parents=True,exist_ok=True);env[key]=str(path)
    stock=payload/'usr/share/kicad'
    library=root/'Runtime/LinuxSystem/kicad-resources/usr/share/kicad'
    env.update(KICAD_STOCK_DATA_HOME=str(stock),KICAD9_TEMPLATE_DIR=str(stock/'template'),
               KICAD9_SYMBOL_DIR=str(library/'symbols'),KICAD9_FOOTPRINT_DIR=str(library/'footprints'),
               KICAD9_3DMODEL_DIR=str(library/'3dmodels'),
               PYTHONHOME=str(payload/'usr'),PYTHONPATH=str(payload/'usr/lib/python3/dist-packages'),
               OMP_NUM_THREADS='2',OPENBLAS_NUM_THREADS='2')
    # No recipient-machine fonts or font cache are required for deterministic exports.
    fonts=state/'fonts.conf'
    fonts.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">'
                     '<fontconfig><dir>'+escape(str(payload/'usr/share/fonts'))+'</dir><cachedir>'
                     +escape(str(state/'cache/fontconfig'))+'</cachedir></fontconfig>',encoding='utf-8')
    env['FONTCONFIG_FILE']=str(fonts)
    resources=payload/'usr/share/opencascade/resources'
    for key,relative in {'CSF_SHMessage':'SHMessage','CSF_XSMessage':'XSMessage',
                         'CSF_StandardDefaults':'StdResource','CSF_PluginDefaults':'StdResource',
                         'CSF_XCAFDefaults':'StdResource','CSF_STEPDefaults':'XSTEPResource',
                         'CSF_IGESDefaults':'XSTEPResource'}.items():env[key]=str(resources/relative)
    libraries=':'.join(map(str,(lib/'x86_64-linux-gnu',lib/'kicad',
        lib/'x86_64-linux-gnu/kicad',lib,lib/'x86_64-linux-gnu/blas',lib/'x86_64-linux-gnu/lapack')))
    return [str(loader),'--library-path',libraries,str(executable)],env


def main():
    if not sys.platform.startswith('linux'):raise RuntimeError('Linux KiCad requires Linux')
    command,env=command_environment()
    os.execve(command[0],[*command,*sys.argv[1:]],env)


if __name__=='__main__':main()
