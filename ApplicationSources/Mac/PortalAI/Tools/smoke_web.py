"""Bounded live web checks, with private reports and isolated cache fixtures."""
import json
from pathlib import Path
import sys
import urllib.error
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'Agent'))
import web_tools as web
from web_state import WebState
from profile_paths import ProfileLocked
from smoke_profile import SmokeProfile


class _SmokeWebState(WebState):
    """An unprofiled cache fixture still belongs to the outer smoke login."""
    def __init__(self, root, profile):
        self.profile=profile
        super().__init__(root, environ={})

    def check(self):
        self.profile.check()
        super().check()


def _fixture_state(profile, name):
    root=profile.path('fixtures/'+name)
    policy=root/'Agent/hardware_profiles.json'
    profile.check()
    policy.parent.mkdir(parents=True,exist_ok=True)
    contents=(profile.root/'Agent/hardware_profiles.json').read_bytes()
    profile.check()
    policy.write_bytes(contents)
    return _SmokeWebState(root,profile)


def _image_signature(data):
    return bool(data.startswith((b'\x89PNG\r\n\x1a\n',b'\xff\xd8\xff',b'GIF87a',b'GIF89a',b'BM')) or
                (data[:4]==b'RIFF' and data[8:12]==b'WEBP') or
                (data[4:8]==b'ftyp' and data[8:12] in (b'avif',b'avis')))


def run_checks(profile):
    report={'checks':[], 'scope':'Live public web; provider access restrictions remain visible.'}
    def check(name, action):
        profile.check()
        try:
            evidence=action()
            profile.check()
            report['checks'].append({'name':name,**evidence})
        except ProfileLocked:
            raise
        except Exception as exc:
            report['checks'].append({'name':name,'passed':False,'error':web._web_error(exc)})

    def public_search():
        with patch.object(web,'WebState',return_value=_fixture_state(profile,'search')):
            result=web.web_search('Python official documentation',3,fresh=True)
        return {'passed':bool(result['results']),'result':result}

    fallback_state=_fixture_state(profile,'fallback')
    fallback_result={}
    def fallback_search():
        original=web.search_duckduckgo
        injected=[]
        def blocked_html(query,limit,*,lite=False):
            if not lite:
                injected.append(True)
                raise urllib.error.HTTPError('https://html.duckduckgo.com/',403,'Injected regression fixture',{},None)
            return original(query,limit,lite=True)
        with patch.object(web,'WebState',return_value=fallback_state),patch.object(web,'search_duckduckgo',side_effect=blocked_html):
            result=web.web_search('Python pathlib documentation',3,fresh=True)
        fallback_result.update(result)
        return {'passed':bool(injected) and result['provider'] in ('bing','duckduckgo-lite') and bool(result['results']),
                'html_403_injected':bool(injected),'result':result}

    def cache_hit():
        if not fallback_result.get('results'):
            return {'passed':False,'reason':'The real Lite request did not produce cacheable results.'}
        with patch.object(web,'WebState',return_value=fallback_state),patch.object(web,'search_duckduckgo',side_effect=AssertionError('Cache hit attempted network access')):
            result=web.web_search('Python pathlib documentation',3)
        return {'passed':result.get('cached') is True}

    def public_page(url, title):
        with patch.object(web,'WebState',return_value=_fixture_state(profile,'pages')):
            result=web.fetch_url(url,max_chars=3000)
        return {'passed':bool(result['text']) and title.casefold() in result['title'].casefold(),
                'url':result['url'],'title':result['title']}

    def public_image():
        with patch.object(web,'WebState',return_value=_fixture_state(profile,'images')):
            found=web.image_search('Eiffel Tower',page_limit=1,candidate_limit=2)
            failures=[]
            for candidate in found.get('images',[])[:2]:
                profile.check()
                try:
                    result=web.download_public_image(candidate['image_url'],query='portalai-web-smoke-eiffel',
                        output_root=str(profile.path('artifacts/images')))
                    profile.check()
                    path=Path(result['path'])
                    if not path.resolve().is_relative_to(profile.path('artifacts/images').resolve()):
                        raise RuntimeError('Downloaded test image is outside its private artifact directory')
                    with path.open('rb') as handle: signature=handle.read(16)
                    profile.check()
                    return {'passed':_image_signature(signature),'provider':found.get('provider'),
                            'source_url':result['source_url'],'path':str(path),'bytes':path.stat().st_size,
                            'content_type':result['content_type'],'earlier_failures':failures}
                except ProfileLocked:raise
                except Exception as exc:failures.append(web._web_error(exc))
            return {'passed':False,'provider':found.get('provider'),'provider_errors':found.get('provider_errors',[]),
                    'download_errors':failures}

    # No real API key is needed or forwarded by these public-provider checks.
    # Profile environment remains intact; only the synthetic WebState has {}.
    with patch.dict(web.os.environ,{'BRAVE_SEARCH_API_KEY':''}):
        check('Live public search',public_search)
        check('Injected HTML 403; real independent/Lite fallback',fallback_search)
        check('Repeated query served from portable cache without network',cache_hit)
        check('Live public page fetch',lambda:public_page('https://www.python.org/doc/','Python'))
        check('Live Wikimedia page fetch',lambda:public_page('https://commons.wikimedia.org/wiki/Main_Page','Wikimedia'))
        check('Real image search and bounded direct image download',public_image)
    profile.check()
    report['passed']=all(item['passed'] for item in report['checks'])
    return report


def main():
    profile=SmokeProfile(ROOT)
    report=run_checks(profile)
    path=profile.save('web-smoke.json',report)
    print(json.dumps({'report':str(path),**report},indent=2))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
