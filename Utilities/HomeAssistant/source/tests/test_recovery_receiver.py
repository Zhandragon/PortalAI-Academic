"""Compatibility tests for the unchanged supplied Recovery 0.1.0 receiver."""
import base64
import hashlib
import importlib.util
from pathlib import Path
import unittest
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec

p=Path(__file__).resolve().parents[1]/'ha/custom_components/portalai_recovery/receiver.py'
s=importlib.util.spec_from_file_location('recovery_receiver',p);r=importlib.util.module_from_spec(s);s.loader.exec_module(r)
class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.key=ec.generate_private_key(ec.SECP256R1());der=self.key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        self.id='a'*32;self.public={'device_id':self.id,'name':'fixture','public_key':base64.b64encode(der).decode(),'fingerprint':hashlib.sha256(der).hexdigest(),'protocol':'portalai-recovery/1','capabilities':['recover_apps']}
        self.now=100;self.receiver=r.Receiver({self.id:r.pairing(self.public)[1]},clock=lambda:self.now)
    def authenticate(self):
        nonce=self.receiver.challenge(self.id)['challenge'];signature=self.key.sign(('PortalAI-Recovery-v1:'+self.id+':'+nonce).encode(),ec.ECDSA(hashes.SHA256()))
        return self.receiver.authenticate({'action':'authenticate','device_id':self.id,'challenge':nonce,'signature':base64.b64encode(signature).decode()})['session']
    def test_scope_is_separate_and_rejects_broader_capabilities(self):
        with self.assertRaises(ValueError):r.pairing({**self.public,'capabilities':['recover_apps','shell']})
        with self.assertRaises(ValueError):r.pairing({k:v for k,v in self.public.items() if k!='protocol'})
        with self.assertRaises(PermissionError):self.receiver.challenge('b'*32)
    def test_authenticated_heartbeat_rejects_replay_and_expires(self):
        token=self.authenticate();payload={'action':'poll','sequence':1,'status':'idle','replies':[]}
        self.receiver.poll(token,payload)
        with self.assertRaises((ValueError,PermissionError)):self.receiver.poll(token,payload)
        self.now+=61
        with self.assertRaises((ValueError,PermissionError)):self.receiver.poll(token,{**payload,'sequence':2})
