"""Dedicated-mail protocol contracts with simulated TLS clients; no messages sent."""
import json
from pathlib import Path
import ssl
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Agent'))
import mission_accounts as accounts
from runtime_policy import atomic_json


class MailAdapterTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.api=accounts.Accounts(self.root)
        atomic_json(self.root/'Agent/hardware_profiles.json',{'storage':{'minimum_free_gib':0,'minimum_free_fraction':0,'output_reserve_gib':0}})
        atomic_json(self.api.base/'profiles.json',{'dedicated':{'backend':'imap-smtp','enabled':True,
            'username':'portal@example.invalid','imap_host':'imap.example.invalid','smtp_host':'smtp.example.invalid',
            'permissions':['email_list','email_read','email_send']}})
        self.mission={'id':'a'*32,'mode':'full','steps':0}
        mock=patch.object(accounts,'vault_read',return_value={'dedicated':{'password':'synthetic-test-password'}})
        mock.start();self.addCleanup(mock.stop)

    def test_smtp_uses_verified_tls_and_checkpoints_acceptance_without_claiming_delivery(self):
        client=MagicMock();client.send_message.return_value={}
        with patch.object(accounts.smtplib,'SMTP_SSL') as factory:
            factory.return_value.__enter__.return_value=client
            params={'to':'recipient@example.invalid','subject':'test','body':'hello'}
            first=self.api.call(self.mission,'dedicated','email_send',params)
            second=self.api.call(self.mission,'dedicated','email_send',params)
            factory.assert_called_once()
            self.assertEqual(factory.call_args.args,('smtp.example.invalid',465))
            tls=factory.call_args.kwargs['context']
            self.assertEqual(tls.verify_mode,ssl.CERT_REQUIRED);self.assertTrue(tls.check_hostname)
        client.send_message.assert_called_once()
        self.assertEqual(first,second);self.assertTrue(first['accepted_by_smtp']);self.assertFalse(first['delivery_confirmed'])
        self.assertNotIn('synthetic-test-password',next((self.api.base/'Journal').glob('*.json')).read_text())

    def test_lost_smtp_reply_is_never_automatically_retried(self):
        client=MagicMock();client.send_message.side_effect=TimeoutError('Connection lost after DATA')
        with patch.object(accounts.smtplib,'SMTP_SSL') as factory:
            factory.return_value.__enter__.return_value=client
            params={'to':'recipient@example.invalid','subject':'test','body':'hello'}
            with self.assertRaisesRegex(RuntimeError,'review journal'):self.api.call(self.mission,'dedicated','email_send',params)
            with self.assertRaisesRegex(RuntimeError,'uncertain outcome'):self.api.call(self.mission,'dedicated','email_send',params)
        client.send_message.assert_called_once()
        journal=json.loads(next((self.api.base/'Journal').glob('*.json')).read_text())
        self.assertEqual(journal['status'],'pending');self.assertIn('message_id',journal)

    def test_imap_message_identity_and_read_only_fetch(self):
        client=MagicMock();client.select.return_value=('OK',[]);client.response.return_value=('UIDVALIDITY',[b'123'])
        client.uid.return_value=('OK',[b'1 2 9'])
        with patch.object(accounts.imaplib,'IMAP4_SSL') as factory:
            factory.return_value.__enter__.return_value=client
            listing=self.api.call(self.mission,'dedicated','email_list')
            self.assertEqual(listing['messages'][-1]['id'],'123:9')
            with self.assertRaisesRegex(ValueError,'UIDVALIDITY'):
                self.api.call(self.mission,'dedicated','email_read',{'id':'122:9'})
            raw=b'From: sender@example.invalid\r\nSubject: Instructions\r\nContent-Type: text/html\r\n\r\n<script>not executed</script>'
            client.uid.side_effect=[('OK',[b'9 (RFC822.SIZE 150)']),('OK',[(b'message',raw)])]
            message=self.api.call(self.mission,'dedicated','email_read',{'id':'123:9'})
            self.assertTrue(message['untrusted_content']);self.assertIn('not executed',message['body'])
            client.uid.assert_called_with('fetch','9','(BODY.PEEK[])')
        client.select.assert_called_with('INBOX',readonly=True)


if __name__=='__main__':unittest.main()
