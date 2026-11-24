"""Pure native receiver checks. No HA process, profile, network, or production key."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'ha/custom_components/portalai_native'
package=types.ModuleType('native_test_package'); package.__path__=[str(SOURCE)]
sys.modules['native_test_package']=package
for name in ('schema','core'):
    spec=importlib.util.spec_from_file_location('native_test_package.'+name,SOURCE/(name+'.py'))
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
from native_test_package import schema
from native_test_package.core import NativeHub

def fixture():
    return json.loads((ROOT/'aoostar-compatibility-20261012/examples/ready-empty-unknown.json').read_text())['snapshot']

class ReceiverTests(unittest.TestCase):
    def setUp(self):
        self.now=100.; self.device='a'*32
        self.approved={self.device:{'fingerprint':'fingerprint'}}
        self.hub=NativeHub(self.approved,{self.device:'fingerprint'},lambda:self.now)
        self.connection=self.hub.attach(self.device)
        self.state=fixture(); self.binding={k:self.state[k] for k in ('view','epoch')}
        self.hub.bind(self.device,self.connection,self.binding)

    def publish(self): return self.hub.publish(self.device,self.connection,self.state)

    def test_empty_chat_and_unknown_counters_are_valid(self):
        self.assertTrue(self.publish()); self.assertIsNone(self.hub.read(self.device)['snapshot']['runtime']['gpu'])

    def test_initial_binding_can_wait_briefly_for_its_first_snapshot(self):
        with self.assertRaises(PermissionError): self.hub.read(self.device)
        self.assertEqual(self.hub.current(self.device)['binding'],self.binding)
        self.now+=.5; self.assertTrue(self.publish())

    def test_no_scope_and_changed_projection_key_are_rejected(self):
        self.hub.grants={}
        with self.assertRaises(PermissionError): self.publish()
        self.hub.grants={self.device:'old-key'}
        with self.assertRaises(PermissionError): self.publish()

    def test_projection_revocation_removes_native_authority_immediately(self):
        self.publish(); self.approved.clear()
        with self.assertRaises(PermissionError): self.hub.read(self.device)

    def test_unbound_view_is_rejected(self):
        self.state['view']='another-view'
        with self.assertRaises(PermissionError): self.publish()

    def test_locked_state_clears_cache_and_cannot_unlock_without_new_binding(self):
        self.publish()
        self.state={**self.binding,'version':2,'revision':2,'account':{'state':'locked','displayName':''}}
        self.assertFalse(self.publish())
        with self.assertRaises(PermissionError): self.hub.read(self.device)
        self.state=fixture(); self.state['revision']=3
        with self.assertRaises(PermissionError): self.publish()

    def test_locked_payload_cannot_contain_private_state(self):
        self.state['account']={'state':'locked','displayName':''}
        with self.assertRaises(ValueError): self.publish()

    def test_out_of_order_revision_rejected(self):
        self.publish()
        for revision in (1,0,3):
            self.state['revision']=revision
            with self.assertRaises(ValueError): self.publish()

    def test_old_socket_cannot_publish_or_clear_new_socket(self):
        new=self.hub.attach(self.device)
        self.assertFalse(self.hub.detach(self.device,self.connection))
        self.hub.bind(self.device,new,self.binding)
        with self.assertRaises(PermissionError): self.publish()
        self.assertFalse(self.hub.invalidate(self.device,self.connection))
        self.assertEqual(self.hub.current(self.device)['connection'],new)

    def test_lease_expiry_clears_cache_and_requires_new_binding(self):
        self.publish(); self.now+=10
        with self.assertRaises(PermissionError): self.hub.read(self.device)
        self.assertIsNone(self.hub.devices[self.device]['snapshot'])
        self.state['revision']=2
        with self.assertRaises(PermissionError): self.publish()

    def test_duplicate_keys_and_nonfinite_json_are_rejected(self):
        for raw in ('{"view":"a","view":"b"}','{"x":NaN}','{"x":Infinity}'):
            with self.assertRaises(ValueError): schema.decode(raw)

    def test_duplicate_list_ids_are_rejected(self):
        samples={'models':{'id':'m','name':'m','kind':'chat','installed':True,'selected':True,'state':'unavailable'},
                 'packages':{'id':'p','name':'p','purpose':'test','state':'unvalidated'}}
        for key,row in samples.items():
            state=fixture(); state[key]=[row,copy.deepcopy(row)]
            with self.assertRaises(ValueError): schema.snapshot(state)
        state=fixture(); state['chat']['current']='c';state['chat']['conversations']=[{'id':'c','title':'c','updated':''}]
        row={'id':'m','role':'user','text':'text','truncated':False};state['chat']['messages']=[row,copy.deepcopy(row)]
        with self.assertRaises(ValueError): schema.snapshot(state)

    def test_window_and_truncation_markers_are_required(self):
        del self.state['chat']['window']
        with self.assertRaises(ValueError): self.publish()

    def test_saved_missing_model_is_observed_not_authorized_for_save(self):
        self.state['settings']['selection']='no-longer-installed'
        self.assertTrue(self.publish())
        self.assertFalse(hasattr(self.hub,'save_settings'))

    def test_entire_multibyte_envelope_budget(self):
        with self.assertRaises(ValueError): schema.encode({'message':'界'*60001})

    def test_snapshot_is_copied(self):
        self.publish();self.state['account']['displayName']='Changed after publication'
        self.assertNotEqual(self.hub.read(self.device)['snapshot']['account']['displayName'],self.state['account']['displayName'])

    def test_real_p256_signature_is_separate_from_projection_protocol(self):
        from cryptography.hazmat.primitives import hashes,serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        key=ec.generate_private_key(ec.SECP256R1()); nonce='n'*64
        der=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        self.approved[self.device]['public_key']=base64.b64encode(der).decode()
        def signed(prefix):return base64.b64encode(key.sign(f'{prefix}:{self.device}:{nonce}'.encode(),ec.ECDSA(hashes.SHA256()))).decode()
        self.hub.authenticate(self.device,nonce,signed('PortalAI-Native-State-v2'))
        with self.assertRaises(Exception):self.hub.authenticate(self.device,nonce,signed('PortalAI-Projection-v1'))

if __name__=='__main__': unittest.main()
