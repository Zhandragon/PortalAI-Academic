"""Relocatable browser-use dependencies and account-local ephemeral state."""
import json
import os
from pathlib import Path
import site
import sys
import uuid


def layer(root):
    from web_runtime import platform_id
    path=Path(root)/'Runtime/BrowserUse'/platform_id()
    manifest=json.loads((path/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('version')!='1.0.7':raise RuntimeError('Repair the pinned browser-use runtime')
    return path/'packages'


def environment(root,profile,env):
    packages=layer(root)
    folder=profile.private('Data/Runtime/BrowserUse')/uuid.uuid4().hex
    folder.mkdir(parents=True,exist_ok=True)
    result=dict(env)
    for key in tuple(result):
        if key.startswith(('BH_','BU_','BROWSER_USE_','BROWSER_HARNESS_')):result.pop(key)
    result.update(ANONYMIZED_TELEMETRY='false',BROWSER_USE_SETUP_LOGGING='false',BROWSER_USE_LOGGING_LEVEL='critical',
                  BROWSER_USE_CONFIG_DIR=str(folder/'config'),BH_HOME=str(folder/'harness'),
                  BH_RUNTIME_DIR=str(folder/'ipc'),BH_TMP_DIR=str(folder/'tmp'),BH_AGENT_WORKSPACE=str(folder/'helpers'),
                  TEMP=str(folder/'temp'),TMP=str(folder/'temp'),PYTHONPATH=str(packages),
                  BROWSER_USE_DISABLE_UPDATE_CHECK='true',PORTALAI_BROWSER_STATE=str(folder))
    (folder/'temp').mkdir(exist_ok=True)
    return result


def prepare(root):
    packages=layer(root)
    sys.path.insert(0,str(packages))
    site.addsitedir(str(packages))
    # The parent sets every upstream state directory before any import.
    if not os.environ.get('PORTALAI_BROWSER_STATE'):raise RuntimeError('Browser worker lacks portable state directory')
    return packages
