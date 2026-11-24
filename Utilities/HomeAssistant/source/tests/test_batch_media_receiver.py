"""Real pairing signatures; larger replies only for dispatched batch reads."""
import base64,hashlib,importlib.util,json,unittest
from pathlib import Path
from types import SimpleNamespace
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec
source=Path(__file__).resolve().parent.parent/'ha/custom_components/portalai_projection/receiver.py'
spec=importlib.util.spec_from_file_location('batch_receiver',source);receiver=importlib.util.module_from_spec(spec);spec.loader.exec_module(receiver)

class MediaReceiverTests(unittest.TestCase):
    def setUp(self):
        key=ec.generate_private_key(ec.SECP256R1())
        der=key.public_key().public_bytes(serialization.Encoding.DER,serialization.PublicFormat.SubjectPublicKeyInfo)
        self.identity,entry=receiver.pairing({'device_id':'d'*32,'name':'Fixture',
            'public_key':base64.b64encode(der).decode(),'fingerprint':hashlib.sha256(der).hexdigest()})
        self.receiver=receiver.Receiver({self.identity:entry})
        nonce=self.receiver.challenge(self.identity)['challenge']
        signature=key.sign(('PortalAI-Projection-v1:'+self.identity+':'+nonce).encode(),ec.ECDSA(hashes.SHA256()))
        token=self.receiver.authenticate({'device_id':self.identity,'challenge':nonce,'signature':base64.b64encode(signature).decode()})['session']
        self.client=SimpleNamespace(session=token,sequence=0)
        def poll(frame,status,replies):
            seq=self.client.sequence+1
            result=self.receiver.poll(token,{'action':'poll','sequence':seq,'frame':frame,'status':status,'replies':replies})
            self.client.sequence=seq
            return result
        self.client.poll=poll;poll(None,{},[])
    def test_large_reply_requires_exact_dispatched_batch_and_cleanup(self):
        p={'operation':'rich_media_batch','protocol':2}
        key=self.receiver.enqueue(self.identity,'native_ui',p);normal=self.receiver.enqueue(self.identity,'native_ui',{'operation':'describe'})
        self.client.poll(None,{},[])
        item={'id':key,'result':{'operation':'rich_media_batch','rich':{'protocol':2,'data':'x'*349528}}}
        body={'action':'poll','sequence':self.client.sequence+1,'frame':None,'status':{},'replies':[{**item,'id':normal}]}
        with self.assertRaisesRegex(ValueError,'too large'):self.receiver.poll(self.client.session,body)
        body['replies']=[{**item,'id':'f'*32}]
        with self.assertRaisesRegex(ValueError,'too large'):self.receiver.poll(self.client.session,body)
        self.client.poll(None,{},[item]);state=self.receiver.devices[self.identity]
        self.assertEqual(state['replies'][key],item)
        self.receiver.forget(self.identity,key);self.assertNotIn(key,state['reply_limits']);self.assertNotIn(key,state['replies'])
    def test_total_reply_budget_and_stop_slots_remain_bounded(self):
        keys=[self.receiver.enqueue(self.identity,'native_ui',{'operation':'rich_media_batch','protocol':2}) for _ in range(2)]
        self.client.poll(None,{},[])
        replies=[{'id':key,'result':{'data':'x'*349528}} for key in keys]
        with self.assertRaisesRegex(ValueError,'Invalid acknowledgements'):
            self.receiver.poll(self.client.session,{'sequence':self.client.sequence+1,'replies':replies})
        self.receiver.forget(self.identity,keys[0]);self.receiver.forget(self.identity,keys[1])
        for _ in range(30):self.receiver.enqueue(self.identity,'native_ui',{'operation':'describe'})
        with self.assertRaises(RuntimeError):self.receiver.enqueue(self.identity,'native_ui',{'operation':'rich_media_batch','protocol':2})
        self.receiver.enqueue(self.identity,'native_ui',{'operation':'invoke','action':'controls_stop'})
        self.receiver.enqueue(self.identity,'native_ui',{'operation':'invoke','action':'controls_exit'})
        self.assertEqual(len(self.receiver.devices[self.identity]['queue']),32)

if __name__=='__main__':unittest.main()
