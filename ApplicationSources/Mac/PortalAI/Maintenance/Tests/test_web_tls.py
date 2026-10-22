import hashlib
import os
from pathlib import Path
import shutil
import ssl
import sys
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'Agent'))
import web_tls


class WebTLSTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Portal TLS fixture ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bundle = self.root/web_tls.BUNDLE_RELATIVE
        self.bundle.parent.mkdir(parents=True)
        shutil.copyfile(ROOT/web_tls.BUNDLE_RELATIVE, self.bundle)

    def test_shipped_bundle_matches_the_pinned_release(self):
        data = self.bundle.read_bytes()
        self.assertEqual(len(data), web_tls.BUNDLE_BYTES)
        self.assertEqual(hashlib.sha256(data).hexdigest(), web_tls.BUNDLE_SHA256)
        self.assertEqual(data.count(b'BEGIN CERTIFICATE'), 121)

    def test_default_context_preserves_recipient_trust_and_adds_portable_roots(self):
        baseline = ssl.create_default_context()
        baseline_roots = set(baseline.get_ca_certs(binary_form=True))
        with patch.object(web_tls.ssl, 'create_default_context', return_value=baseline) as factory:
            context = web_tls.default_context(self.root)
        factory.assert_called_once_with()
        self.assertIs(context, baseline)
        self.assertTrue(baseline_roots.issubset(set(context.get_ca_certs(binary_form=True))))
        self.assertGreaterEqual(context.cert_store_stats()['x509_ca'], 121)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_portable_context_ignores_host_ca_environment_without_changing_it(self):
        with patch.dict(os.environ, {'SSL_CERT_FILE': str(self.root/'missing.pem'),
                                     'SSL_CERT_DIR': str(self.root/'missing-certs')}):
            before = dict(os.environ)
            context = web_tls.portable_context(self.root)
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(context.cert_store_stats()['x509_ca'], 121)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_missing_truncated_tampered_or_oversized_bundle_fails_closed(self):
        original = self.bundle.read_bytes()
        for data in (None, original[:-1], bytes([original[0] ^ 1])+original[1:], original+b'x'):
            if data is None:
                self.bundle.unlink()
            else:
                self.bundle.write_bytes(data)
            for factory in (web_tls.default_context, web_tls.portable_context):
                with self.assertRaises(web_tls.TrustBundleError):
                    factory(self.root)

    def test_verified_data_is_loaded_from_memory_without_a_second_path_read(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        def make_context():
            self.bundle.write_bytes(b'changed after verification')
            return context
        with patch.object(web_tls.ssl, 'create_default_context', side_effect=make_context):
            result = web_tls.default_context(self.root)
        self.assertEqual(result.cert_store_stats()['x509_ca'], 121)
        with self.assertRaises(web_tls.TrustBundleError):
            web_tls.default_context(self.root)

    def test_certificate_errors_are_structured_without_sensitive_exception_text(self):
        certificate = ssl.SSLCertVerificationError(1, 'private token or path must not be echoed')
        certificate.verify_code = 10
        for error in (certificate, urllib.error.URLError(certificate)):
            detail = web_tls.certificate_error(error)
            self.assertEqual(detail['category'], 'tls_certificate_error')
            self.assertEqual(detail['verify_code'], 10)
            self.assertNotIn('private token', detail['message'])

    def test_nested_certificate_cause_is_classified_but_other_ssl_errors_are_not(self):
        certificate = ssl.SSLCertVerificationError(1, 'fixture')
        outer = RuntimeError('wrapper')
        outer.__cause__ = urllib.error.URLError(certificate)
        self.assertEqual(web_tls.certificate_error(outer)['category'], 'tls_certificate_error')
        for error in (ssl.SSLError('handshake failure'), urllib.error.URLError('certificate words'),
                      urllib.error.HTTPError('https://example.com', 403, 'Forbidden', {}, None)):
            self.assertIsNone(web_tls.certificate_error(error))

    def test_exception_cycles_are_bounded(self):
        first = RuntimeError('first')
        second = RuntimeError('second')
        first.__cause__ = second
        second.__cause__ = first
        self.assertIsNone(web_tls.certificate_error(first))


if __name__ == '__main__':
    unittest.main()
