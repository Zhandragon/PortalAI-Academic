"""Model opt-in, package identity, auth boundaries and native publication."""
from pathlib import Path
import copy, hashlib, importlib.util, io, json, sys, tempfile, threading, unittest, urllib.request

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'InstallerSources/Windows'))
import installer_core as core
import model_choices
spec=importlib.util.spec_from_file_location('complete_models',ROOT/'InstallerSources/Models/complete_models.py')
models=importlib.util.module_from_spec(spec);spec.loader.exec_module(models)

DATA=b'synthetic model fixture, not executable'
SHA=hashlib.sha256(DATA).hexdigest()
def component(identity='example'):
    artifact=dict(id=identity,url='https://huggingface.co/example/model/resolve/pinned/fixture.gguf',bytes=len(DATA),sha256=SHA,format='file',
        members=[dict(dest='PortalAI Windows/LLM/models/fixture.gguf',bytes=len(DATA),sha256=SHA)])
    review=dict(license='Fixture license',restrictions='Fixture only',license_url='https://example.test/license',sources=[artifact['url']],artifacts=[{k:artifact[k] for k in ('id','sha256','bytes')}])
    review['review_digest']=model_choices.digest(review)
    return dict(id=identity,label='Example model',required=False,artifacts=[artifact],model_choice=review)

class Response(io.BytesIO):
    status=200
    headers={}

class Opener:
    def __init__(self):self.requests=[]
    def open(self,request,timeout):self.requests.append(request);return Response(DATA)

class CompleteModels(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.catalog=dict(schema=1,edition='Full',version='test',components=[component()])
        self.request=dict(selected=['example'],consent={'example':component()['model_choice']['review_digest']})
    def tearDown(self):core.set_huggingface_token('');self.tmp.cleanup()
    def test_native_all_models_are_opt_in(self):
        self.assertEqual(models.chosen(self.catalog,[])[0],[])
        with self.assertRaises(ValueError):models.install(self.root,self.root,self.catalog,dict(selected=['example'],consent={}))
        self.assertFalse((self.root/'LLM').exists())
    def test_native_publication_keeps_models_under_application_root(self):
        opener=Opener();result=models.install(self.root,self.root,self.catalog,self.request,opener=opener)
        self.assertEqual(result['new_files'],1)
        self.assertEqual((self.root/'LLM/models/fixture.gguf').read_bytes(),DATA)
        self.assertFalse((self.root/'PortalAI Windows').exists())
        self.assertFalse((self.root/'Private').exists())
        self.assertEqual(len(opener.requests),1)
        models.install(self.root,self.root,self.catalog,self.request,opener=opener)
        self.assertEqual(len(opener.requests),1,'Verified existing models must be reused')
    def test_native_existing_different_model_is_preserved(self):
        p=self.root/'LLM/models/fixture.gguf';p.parent.mkdir(parents=True);p.write_bytes(b'keep existing')
        with self.assertRaises(ValueError):models.install(self.root,self.root,self.catalog,self.request,opener=Opener())
        self.assertEqual(p.read_bytes(),b'keep existing')
    def test_native_academic_rejects_full_catalog(self):
        (self.root/'Agent').mkdir();(self.root/'Agent/academic_policy.py').touch()
        with self.assertRaises(ValueError):models.install(self.root,self.root,self.catalog,self.request,opener=Opener())
    def overlay(self,edition='Full'):
        manifest=dict(schema=1,status='RELEASED',upgrade=dict(edition=edition),components=[])
        raw=json.dumps(manifest).encode();(self.root/'release.json').write_bytes(raw)
        overlay=dict(schema=1,edition=edition,base_release_sha256=hashlib.sha256(raw).hexdigest(),components=[component()])
        (self.root/'model-overlay.json').write_text(json.dumps(overlay));return overlay
    def test_overlay_is_bound_to_exact_base_manifest(self):
        self.overlay();self.assertEqual(len(core.read_manifest(self.root)['components']),1)
        with (self.root/'release.json').open('ab') as f:f.write(b' ')
        with self.assertRaises(core.InstallError):core.read_manifest(self.root)
    def test_overlay_cannot_make_models_required(self):
        overlay=self.overlay();overlay['components'][0]['required']=True
        (self.root/'model-overlay.json').write_text(json.dumps(overlay))
        with self.assertRaises(core.InstallError):core.read_manifest(self.root)
    def test_academic_overlay_cannot_add_alternate_models(self):
        overlay=self.overlay('Academic');overlay['components'][0]['label']='Alternate model'
        (self.root/'model-overlay.json').write_text(json.dumps(overlay))
        with self.assertRaises(core.InstallError):core.read_manifest(self.root)
    def test_hf_token_is_scoped_to_approved_origin(self):
        artifact=component()['artifacts'][0];artifact['authentication']='huggingface';opener=Opener()
        core.set_huggingface_token('synthetic-test-token')
        core.fetch(artifact,self.root/'cache',threading.Event(),lambda *a:None,opener=opener)
        self.assertEqual(opener.requests[0].get_header('Authorization'),'Bearer synthetic-test-token')
        for p in self.root.rglob('*'):
            if p.is_file():self.assertNotIn(b'synthetic-test-token',p.read_bytes())
        artifact['url']='https://example.test/model';artifact['sha256']='0'*64
        with self.assertRaises(core.InstallError):core.fetch(artifact,self.root/'cache',threading.Event(),lambda *a:None,opener=opener)
        self.assertEqual(len(opener.requests),1)
    def test_hf_token_is_removed_from_cdn_redirects(self):
        request=urllib.request.Request('https://huggingface.co/model',headers={'Authorization':'Bearer synthetic'})
        redirected=core.HTTPSOnly().redirect_request(request,None,302,'',{},'https://cdn.example.test/object')
        self.assertIsNone(redirected.get_header('Authorization'))
    def test_gated_download_requires_recipient_token(self):
        artifact=component()['artifacts'][0];artifact['authentication']='huggingface';opener=Opener()
        with self.assertRaises(core.InstallError):core.fetch(artifact,self.root/'cache',threading.Event(),lambda *a:None,opener=opener)
        self.assertEqual(opener.requests,[])
    def test_completed_cache_cleanup_preserves_partial_and_unrelated_files(self):
        cache=self.root/'downloads';cache.mkdir()
        (cache/(SHA+'.download')).write_bytes(DATA)
        (cache/(SHA+'.partial')).write_bytes(b'partial')
        (cache/'keep.txt').write_text('keep')
        self.assertEqual(core.completed_download_cleanup(cache,[component()['artifacts'][0]],lambda *a:None),len(DATA))
        self.assertFalse((cache/(SHA+'.download')).exists())
        self.assertEqual((cache/(SHA+'.partial')).read_bytes(),b'partial')
        self.assertEqual((cache/'keep.txt').read_text(),'keep')

if __name__=='__main__':unittest.main()
