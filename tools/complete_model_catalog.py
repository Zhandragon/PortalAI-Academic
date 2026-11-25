"""Build small, pinned model catalogs and Windows manifest overlays.

Model weights are downloaded only when selected by the recipient. The original
native application archives remain intact inside each download bundle.
"""
from pathlib import Path
import copy, hashlib, json, sys, zipfile


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=True)+'\n').encode()


def review(component):
    current=component['model_choice']
    current.pop('review_digest',None)
    current['sources']=sorted({a['url'] for a in component['artifacts']})
    current['artifacts']=[{k:a[k] for k in ('id','sha256','bytes')} for a in component['artifacts']]
    current['review_digest']=hashlib.sha256(json.dumps(current,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def model_member(component_id, row):
    dest=row['dest']
    if not dest.startswith('PortalAI Windows/'):
        return False
    if component_id=='piper-voice':
        return '/Voice/Piper/models/' in dest or dest.endswith(('/piper/hebrew/nakdimon.onnx','/piper/tashkeel/model.onnx'))
    if component_id=='protein-runtime':
        return '/vanilla_model_weights/' in dest
    # Other reviewed model groups contain model files and their supporting data.
    # Do not introduce runtime wheels or executable repository code on another OS.
    return Path(dest).suffix.casefold() not in ('.whl','.exe','.dll','.pyd','.so','.dylib','.py','.pyc','.bat','.cmd','.ps1')


def prepare(repo, windows_archive, edition):
    repo=Path(repo)
    with zipfile.ZipFile(windows_archive) as archive:
        base_release=archive.read('release.json');base_storage=archive.read('storage-plan.json')
        manifest=json.loads(base_release)
        storage=json.loads(base_storage)
    assert manifest['upgrade']['edition']==edition
    source=json.loads((repo/'InstallerSources/Models/model-additions.json').read_text('utf-8'))
    overlay={};changes=[];storage_changes=[]
    original_ids={c['id'] for c in manifest['components']}
    for item in source['additions']:
        if edition=='Academic' and item['full_only']:
            raise ValueError('Academic catalog contains a Full-only model')
        component=copy.deepcopy(item['component'])
        assert component['required'] is False
        if component['id'] in original_ids:
            existing=next(c for c in manifest['components'] if c['id']==component['id'])
            pins=lambda c:sorted((m['dest'],m['bytes'],m['sha256']) for a in c['artifacts'] for m in a['members'])
            assert pins(existing)==pins(component),'Existing model pins differ'
            existing['required']=False
            existing['model_choice']=component['model_choice']
            review(existing)
            changes.append(existing)
            continue
        for artifact in component['artifacts']:
            if 'inline_utf8' in artifact:
                data=artifact.pop('inline_utf8').encode()
                assert len(data)==artifact['bytes'] and hashlib.sha256(data).hexdigest()==artifact['sha256']
                overlay[artifact['bundled_file']]=data
        manifest['components'].append(component)
        changes.append(component)
        storage_row=dict(id=component['id'],label=component['label'],required=False,
            depends_on=component.get('depends_on',[]),
            installed_bytes=sum(m['bytes'] for a in component['artifacts'] for m in a['members']),
            files=sum(len(a['members']) for a in component['artifacts']),
            downloads=[{k:a[k] for k in ('sha256','bytes')} for a in component['artifacts']])
        storage['components'].append(storage_row);storage_changes.append(storage_row)
    manifest['complete_model_catalog']=dict(version=source['version'],models_embedded=False,
        added_components=[i['component']['id'] for i in source['additions']])
    assert {r['id'] for r in storage['components']}=={r['id'] for r in manifest['components']}
    overlay['model-overlay.json']=encoded(dict(schema=1,edition=edition,version=source['version'],
        base_release_sha256=hashlib.sha256(base_release).hexdigest(),base_storage_sha256=hashlib.sha256(base_storage).hexdigest(),
        components=changes,storage_components=storage_changes))
    native=[]
    for original in manifest['components']:
        if 'model_choice' not in original:continue
        component=copy.deepcopy(original);artifacts=[]
        for artifact in component['artifacts']:
            artifact['members']=[r for r in artifact['members'] if model_member(component['id'],r)]
            if artifact['members']:artifacts.append(artifact)
        if not artifacts:continue
        component['artifacts']=artifacts;component['required']=False
        review(component);native.append(component)
    ids={c['id'] for c in native}
    for component in native:
        component['depends_on']=[d for d in component.get('depends_on',[]) if d in ids]
    return overlay,dict(schema=1,edition=edition,version=source['version'],components=native,
        notice='Model files are portable; native runtime support varies by OS. Mac/Linux remain experimental. No Windows runtime packages are installed by this model chooser.')
