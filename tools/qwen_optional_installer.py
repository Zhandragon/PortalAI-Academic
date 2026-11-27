"""Add opt-in publisher links to a release catalog, never to its payload.

Used for the identical installer catalog shipped through GitHub, Payhip and itch.
No network or model loading occurs during release preparation.
"""
import copy
import json
from pathlib import Path
import sys

def add_optional_qwen(release, repo):
    repo=Path(repo);sys.path.insert(0,str(repo/'InstallerSources/Windows'))
    from model_choices import apply_policy
    component=json.loads((repo/'InstallerSources/Windows/qwen_image_edit_component.json').read_text())
    result=copy.deepcopy(release)
    if any(c['id']==component['id'] for c in result['components']):raise ValueError('Duplicate Qwen installer component')
    result['components'].append(component)
    result=apply_policy(result)
    optional=next(c for c in result['components'] if c['id']==component['id'])
    if optional.get('required') or not optional.get('model_choice'):raise ValueError('Qwen download must require explicit model review')
    destinations={m['dest'] for a in optional['artifacts'] for m in a['members']}
    if any(row['dest'] in destinations for row in result['payload']['members']):
        raise ValueError('Qwen weights must not be embedded in the application payload')
    for other in result['components']:
        if other['id']!=optional['id'] and optional['id'] in other.get('depends_on',[]):
            raise ValueError('Other components must not select Qwen as a dependency')
    from installer_core import plan
    chosen,artifacts,files,space=plan(result,[])
    if any(c['id']==optional['id'] for c in chosen):raise ValueError('Default installation selected Qwen')
    return result
