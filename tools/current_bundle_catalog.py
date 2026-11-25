"""Build current suite choices without circular hashes for bundle self-copies."""
from pathlib import Path
import copy,hashlib,json

def current_catalog(raw,edition,version):
    catalog=json.loads(raw);assets=[]
    pins=json.loads((Path(__file__).with_name('current-native-installers.json')).read_text(encoding='utf-8'))
    editions=('Full','Academic') if edition=='Full' else ('Academic',)
    for asset in catalog['assets']:
        if asset['edition']=='Full' and edition=='Academic':continue
        if asset['kind']!='installer':assets.append(asset);continue
        # The other-edition application uses its current original native payload.
        app=copy.deepcopy(asset);app['id']=app['id'].replace('installer-','application-',1)
        app['application_only']=True
        if app['platform']=='Windows':app.update(pins[app['edition']])
        assets.append(app)
    for owner in editions:
        repo='Zhandragon/PortalAI'+('-Academic' if owner=='Academic' else '')
        for platform in ('Windows','Mac','Linux','Universal'):
            name=f'PortalAI-{owner}-{platform}-Bundle-{version}.zip'
            tag='v'+version
            # Estimates are used only for the initial UI. resolve_catalog requires
            # the exact published release asset digest before downloading/copying.
            estimate={'Windows':800_000_000,'Mac':750_000_000,'Linux':700_000_000,'Universal':1_999_000_000}[platform]
            assets.append(dict(id='installer-'+owner.lower()+'-'+platform.lower(),kind='installer',edition=owner,platform=platform,
                file=name,bytes=estimate,sha256=hashlib.sha256((repo+'/'+tag+'/'+name).encode()).hexdigest(),expanded_bytes=0,
                repository=repo,tag=tag,url='https://github.com/'+repo+'/releases/download/'+tag+'/'+name,
                private=owner=='Full',resolve_release=True,copy_only=True,bundle_copy=True))
    catalog.update(catalog_version=version,assets=assets)
    return (json.dumps(catalog,indent=2)+'\n').encode()
