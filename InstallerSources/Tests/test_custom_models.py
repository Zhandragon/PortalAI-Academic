import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Windows'))
import custom_models as custom
import model_choices
import installer_core as core


def gguf(architecture='qwen3', overlap=False, template=True):
    def string(value):
        b=value.encode();return struct.pack('<Q',len(b))+b
    meta={'general.architecture':architecture, 'tokenizer.ggml.model':'gpt2',
          'qwen3.block_count':1,'qwen3.context_length':8192,'qwen3.embedding_length':128,
          'qwen3.attention.head_count':2,'qwen3.attention.head_count_kv':1}
    if template:meta['tokenizer.chat_template']='{{ messages }}'
    b=b'GGUF'+struct.pack('<IQQ',3,3,len(meta))
    for key,value in meta.items():
        b+=string(key)+struct.pack('<I',8 if isinstance(value,str) else 4)
        b+=string(value) if isinstance(value,str) else struct.pack('<I',value)
    for i,name in enumerate(('token_embd.weight','output_norm.weight','blk.0.attn_q.weight')):
        b+=string(name)+struct.pack('<IQIQ',1,128,0,0 if overlap else i*512)
    b+=b'\0'*((-len(b))%32)+b'\0'*1536
    return b


class CustomModels(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'model.gguf'
        self.path.write_bytes(gguf())
        self.request=dict(url='https://example.com/choice.gguf',license_url='https://example.com/LICENSE',
                          label='Different compatible model',bytes=self.path.stat().st_size,
                          sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(),variant='standard',accepted=True)

    def test_structure_and_unsupported_inputs(self):
        self.assertEqual(custom.inspect_gguf(self.path)['layers'],1)
        for data in (gguf(architecture='llama'),gguf(overlap=True),gguf(template=False),gguf()[:-1],b'GGUF'+b'\xff'*1200):
            self.path.write_bytes(data)
            with self.assertRaises(ValueError):custom.inspect_gguf(self.path)

    def test_register_only_valid_records_and_verify_changes(self):
        manifest,key=model_choices.with_custom_model({'components':[]},self.request)
        definition=manifest['generated_receipts'][0]
        target=self.root/definition['data']['path'];target.parent.mkdir(parents=True);target.write_bytes(self.path.read_bytes())
        record=self.root/'Maintenance/Imports'/f'{key}.json';record.parent.mkdir(parents=True)
        record.write_text(json.dumps({**definition['data'],'verified':True}))
        policy={'models':[]};custom.register_installed(self.root,policy)
        self.assertEqual(policy['models'][0]['id'],key)
        self.assertFalse(policy['models'][0]['automatic'])
        custom.verify_selected(target,policy['models'][0])
        with target.open('r+b') as f:f.seek(-1,2);f.write(b'x')
        with self.assertRaisesRegex(ValueError,'checksum'):custom.verify_selected(target,policy['models'][0])
        record.write_text(json.dumps({**definition['data'],'path':'../../elsewhere','verified':True}))
        policy={'models':[]};custom.register_installed(self.root,policy)
        self.assertEqual(policy['models'],[])

    def package(self):
        package=self.root/'package';package.mkdir()
        content=b'def register(*args): pass\n'
        dest='PortalAI Windows/Agent/executable_recovery.py'
        with zipfile.ZipFile(package/'payload.zip','w') as z:z.writestr(dest,content)
        archive=(package/'payload.zip').read_bytes()
        manifest={'schema':1,'status':'RELEASED','release':'test','components':[],
                  'payload':{'id':'payload','file':'payload.zip','bytes':len(archive),
                             'sha256':hashlib.sha256(archive).hexdigest(),'members':[
                                 {'member':dest,'dest':dest,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()}]}}
        (package/'release.json').write_text(json.dumps(manifest))
        return package,manifest

    def test_real_installer_validates_custom_before_publication(self):
        package,_=self.package();target=self.root/'installed'
        with patch.object(core,'download_artifact',return_value=self.path):
            result=core.install(package,target,[],custom_model=self.request)
        self.assertIn('custom-'+self.request['sha256'],result['components'])
        app=target/'PortalAI Windows';policy={'models':[]};custom.register_installed(app,policy)
        self.assertEqual(len(policy['models']),1)
        self.path.write_bytes(gguf(architecture='llama'))
        bad=self.root/'bad'
        with patch.object(core,'download_artifact',return_value=self.path),self.assertRaises(ValueError):
            core.install(package,bad,[],custom_model=self.request)
        self.assertFalse(bad.exists())

    def test_license_gate_stops_before_downloads(self):
        package,manifest=self.package()
        manifest['components']=[{'id':'musicgen-cpu-models','required':True,'artifacts':[]}]
        manifest=model_choices.apply_policy(manifest)
        (package/'release.json').write_text(json.dumps(manifest))
        with patch.object(core,'download_artifact') as download,self.assertRaises(ValueError):
            core.install(package,self.root/'not-created',['musicgen-cpu-models'])
        download.assert_not_called()
        self.assertFalse((self.root/'not-created').exists())


if __name__=='__main__':unittest.main()
