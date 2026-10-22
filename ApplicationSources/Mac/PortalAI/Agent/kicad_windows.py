"""Windows KiCad resources and state remain on the portable drive."""
from pathlib import Path
from profile_paths import private_path
from runtime_policy import portable_env


def command_environment(root, *, payload=None):
    root = Path(root).resolve()
    state = private_path(root, 'Data/Science/KiCad')
    payload = Path(payload) if payload is not None else root/'Tools/KiCad'
    executable = payload/'bin/kicad-cli.exe'
    stock = payload/'share/kicad'
    for file in (executable, stock/'symbols/Device.kicad_sym',
                 stock/'footprints/Resistor_SMD.pretty/R_0805_2012Metric.kicad_mod'):
        if not file.is_file(): raise RuntimeError('Portable Windows KiCad payload is incomplete: '+str(file))
    env = portable_env(root)
    env.pop('KICAD_RUN_FROM_BUILD_DIR', None)
    for key, relative in {'HOME':'home', 'USERPROFILE':'home', 'APPDATA':'config',
        'LOCALAPPDATA':'cache', 'XDG_CONFIG_HOME':'config', 'XDG_CACHE_HOME':'cache',
        'KICAD_CONFIG_HOME':'config/kicad', 'KICAD_CACHE_HOME':'cache',
        'KICAD_DOCUMENTS_HOME':'documents', 'TEMP':'tmp', 'TMP':'tmp', 'TMPDIR':'tmp'}.items():
        path = state/relative; path.mkdir(parents=True, exist_ok=True); env[key] = str(path)
    env.update(KICAD_STOCK_DATA_HOME=str(stock), KICAD9_TEMPLATE_DIR=str(stock/'template'),
        KICAD9_SYMBOL_DIR=str(stock/'symbols'), KICAD9_FOOTPRINT_DIR=str(stock/'footprints'),
        KICAD9_3DMODEL_DIR=str(stock/'3dmodels'), OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='2')
    return [str(executable)], env
