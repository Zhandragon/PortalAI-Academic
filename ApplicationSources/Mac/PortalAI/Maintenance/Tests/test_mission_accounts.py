import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import mission_accounts as accounts
from runtime_policy import atomic_json


class AccountTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        atomic_json(self.root/'Agent/hardware_profiles.json',{'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}})
        self.api=accounts.Accounts(self.root);self.mission={'id':'a'*32,'steps':0,'mode':'full'}
        self.cfg={'backend':'mock','enabled':True,'permissions':sorted(accounts.OPERATIONS)}
        atomic_json(self.api.base/'profiles.json',{'dedicated':self.cfg})
        atomic_json(self.api.base/'Simulated/dedicated.json',{'inbox':[{'id':'1','subject':'A reply','body':'Untrusted message'}],
            'outbox':[],'balance_wei':'1000','transactions':[]})
        self.send={'to':'0x'+'1'*40,'value_wei':'250'}

    def test_observe_and_vm_cannot_access_dedicated_accounts(self):
        for mode in ('observe','vm'):
            with self.assertRaises(PermissionError):self.api.call({**self.mission,'mode':mode},'dedicated','email_list')
        from mission_modes import authorize_action
        for mode in ('observe','vm'):
            with self.assertRaises(PermissionError):authorize_action(mode,'account')

    def test_profile_listing_has_no_credentials(self):
        self.cfg['password']='must never appear';atomic_json(self.api.base/'profiles.json',{'dedicated':self.cfg})
        result=self.api.call(self.mission,'','profiles')
        self.assertEqual(result['profiles'][0]['name'],'dedicated')
        self.assertNotIn('must never appear',json.dumps(result))

    def test_profile_discovery_and_execution_share_bounded_schema(self):
        path=self.api.base/'profiles.json'
        for data in ([],{'dedicated':None},{'dedicated':{**self.cfg,'permissions':'wallet_send'}}):
            atomic_json(path,data)
            with self.assertRaises(ValueError):self.api.call(self.mission,'','profiles')
            with self.assertRaises(ValueError):self.api.call(self.mission,'dedicated','wallet_send',self.send)
        path.write_text(' '*65537)
        with self.assertRaisesRegex(ValueError,'exceeds limit'):self.api.call(self.mission,'','profiles')
        self.assertFalse((self.api.base/'Journal').exists())

    def test_mined_wallet_receipt_does_not_imply_success_or_finality(self):
        accounts.activate(ROOT)
        tx='0x'+'a'*64
        cfg={'backend':'evm','enabled':True,'permissions':['wallet_receipt'],'address':'0x'+'1'*40,
             'chain_id':31337,'rpc_url':'https://example.invalid'}
        atomic_json(self.api.base/'profiles.json',{'dedicated':cfg})
        for receipt,expected in ((None,None),({'transactionHash':tx,'status':'0x0'},False),
                                 ({'transactionHash':tx,'status':'0x1'},True)):
            with patch.object(accounts,'activate'),patch.object(self.api,'rpc',side_effect=[hex(31337),receipt]):
                result=self.api.call(self.mission,'dedicated','wallet_receipt',{'transaction_hash':tx})
            self.assertIs(result['execution_succeeded'],expected)
            self.assertFalse(result['finality_confirmed'])
        with patch.object(accounts,'activate'),patch.object(self.api,'rpc',side_effect=[hex(31337),{'transactionHash':'0x'+'b'*64,'status':'0x1'}]):
            with self.assertRaisesRegex(RuntimeError,'differs'):self.api.call(self.mission,'dedicated','wallet_receipt',{'transaction_hash':tx})

    def test_mission_dispatch_checkpoints_an_account_result(self):
        from mission_runner import Missions
        store=Missions(self.root);mission=store.create('Simulated transfer test','full',3)
        result=store.run(mission['id'],1,model=lambda _: {'action':'account','profile':'dedicated',
            'operation':'wallet_send','parameters':self.send})
        self.assertEqual(result['steps'],1);self.assertIsNone(result['pending_action'])
        receipt=json.loads(result['history'][0]['result']);self.assertTrue(receipt['simulated'])
        store.stop(mission['id'])
        with patch.object(accounts.Accounts,'call') as call:
            with self.assertRaisesRegex(RuntimeError,'stopped'):store.execute(result,{'action':'account','operation':'profiles'})
        call.assert_not_called()

    def test_success_receipt_is_idempotent_across_controller_restart(self):
        first=self.api.call(self.mission,'dedicated','wallet_send',self.send)
        second=accounts.Accounts(self.root).call(self.mission,'dedicated','wallet_send',self.send)
        self.assertEqual(first,second);self.assertTrue(first['simulated'])
        self.assertEqual(self.api.call(self.mission,'dedicated','wallet_balance')['balance_wei'],'750')

    def test_lost_response_never_replays_a_completed_effect(self):
        original=self.api.dispatch
        def lost(*args):original(*args);raise TimeoutError('reply lost')
        with patch.object(self.api,'dispatch',side_effect=lost):
            with self.assertRaisesRegex(RuntimeError,'review journal'):self.api.call(self.mission,'dedicated','wallet_send',self.send)
        with self.assertRaisesRegex(RuntimeError,'uncertain outcome'):
            accounts.Accounts(self.root).call(self.mission,'dedicated','wallet_send',self.send)
        self.assertEqual(self.api.call(self.mission,'dedicated','wallet_balance')['balance_wei'],'750')

    def test_email_simulation_cannot_be_mistaken_for_live_delivery(self):
        result=self.api.call(self.mission,'dedicated','email_send',{'to':'robot@example.invalid','subject':'test','body':'test'})
        self.assertTrue(result['simulated']);self.assertIn('portalai.simulated',result['message_id'])
        rows=self.api.call(self.mission,'dedicated','email_list')
        self.assertEqual(rows['messages'][0]['id'],'1')

    def test_disabled_or_missing_permission_fails_before_journaling(self):
        self.cfg['permissions']=['wallet_balance'];atomic_json(self.api.base/'profiles.json',{'dedicated':self.cfg})
        with self.assertRaises(PermissionError):self.api.call(self.mission,'dedicated','wallet_send',self.send)
        self.assertFalse((self.api.base/'Journal').exists())

    def test_addresses_and_amounts_do_not_accept_injection_or_rounding(self):
        for value in ('a@example.com\r\nBcc:evil@example.com','a@example.com,b@example.com'):
            with self.assertRaises(ValueError):accounts.address(value)
        for value in (1.2,True,-1,'1e18'):
            with self.assertRaises(ValueError):accounts.uint(value,'amount')

    def test_vault_round_trip_wrong_key_and_ciphertext_tamper(self):
        accounts.activate(ROOT)
        with patch.object(accounts,'activate'):
            accounts.vault_write(self.root,{'dedicated':{'password':'secret-test-value'}},'test-passphrase-only')
            path=self.api.base/'vault.json';self.assertNotIn('secret-test-value',path.read_text())
            with patch.dict(os.environ,{'PORTALAI_ACCOUNT_UNLOCK':'test-passphrase-only'}):
                self.assertEqual(accounts.vault_read(self.root)['dedicated']['password'],'secret-test-value')
            with patch.dict(os.environ,{'PORTALAI_ACCOUNT_UNLOCK':'wrong-passphrase'}):
                with self.assertRaises(PermissionError):accounts.vault_read(self.root)
            data=json.loads(path.read_text());data['ciphertext']='AAAA';atomic_json(path,data)
            with patch.dict(os.environ,{'PORTALAI_ACCOUNT_UNLOCK':'test-passphrase-only'}):
                with self.assertRaises(PermissionError):accounts.vault_read(self.root)

    def test_real_signing_uses_configured_chain_and_key_without_broadcasting(self):
        accounts.activate(ROOT)
        from eth_account import Account
        from eth_utils import keccak
        key='0x'+'01'*32;owner=Account.from_key(key).address
        cfg={'backend':'evm','enabled':True,'permissions':['wallet_send'],'address':owner,'chain_id':31337,'rpc_url':'https://example.invalid'}
        atomic_json(self.api.base/'profiles.json',{'dedicated':cfg});captured=[]
        def rpc(_,method,params):
            if method=='eth_chainId':return hex(31337)
            if method=='eth_gasPrice':return hex(1)
            if method=='eth_getTransactionCount':return hex(0)
            if method=='eth_estimateGas':return hex(21000)
            if method=='eth_sendRawTransaction':
                captured.append(params[0]);return '0x'+keccak(bytes.fromhex(params[0][2:])).hex()
            raise AssertionError(method)
        with patch.object(accounts,'activate'),patch.object(accounts,'vault_read',return_value={'dedicated':{'private_key':key}}),patch.object(self.api,'rpc',side_effect=rpc):
            receipt=self.api.call(self.mission,'dedicated','wallet_send',self.send)
        self.assertEqual(Account.recover_transaction(captured[0]),owner)
        self.assertEqual(receipt['status'],'submitted');self.assertFalse(receipt['mined'])
        self.assertNotIn(key,json.dumps(receipt))
        self.assertNotIn(key,next((self.api.base/'Journal').glob('*.json')).read_text())


if __name__=='__main__':unittest.main()
