"""Verified portable Mozilla roots, added to normal recipient TLS trust.

No environment variables or process-wide SSL defaults are changed. A broken
bundled asset fails closed. This module never disables time, chain or hostname
verification and never downloads trust material while handling a web request.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import ssl
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_VERSION = '2026.7.22'
BUNDLE_RELATIVE = 'Runtime/Certificates/cacert.pem'
BUNDLE_BYTES = 240216
BUNDLE_SHA256 = '9cc2a774b5198dcff14d9be1e66091f538975d867ce029a96bce15a55dfd730f'


class TrustBundleError(RuntimeError):
    """The pinned portable trust material is missing or has changed."""


def _bundle_data(root=ROOT):
    path = Path(root) / BUNDLE_RELATIVE
    try:
        # Read the verified bytes directly into OpenSSL below, avoiding a
        # separate path-open after verification and limiting damaged inputs.
        with path.open('rb') as source:
            data = source.read(BUNDLE_BYTES + 1)
    except OSError as exc:
        raise TrustBundleError('The portable HTTPS certificate bundle is unavailable.') from exc
    if len(data) != BUNDLE_BYTES or hashlib.sha256(data).hexdigest() != BUNDLE_SHA256:
        raise TrustBundleError('The portable HTTPS certificate bundle failed its integrity check.')
    return data.decode('ascii')


def default_context(root=ROOT):
    """Keep OS/enterprise trust and add the pinned Mozilla root certificates."""
    data = _bundle_data(root)
    context = ssl.create_default_context()
    context.load_verify_locations(cadata=data)
    return context


def portable_context(root=ROOT):
    """Explicit diagnostic context using only pinned roots, with full TLS checks.

    Normal web requests use default_context so managed-computer trust remains
    available. This helper does not read SSL_CERT_FILE or the Windows store.
    """
    data = _bundle_data(root)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=data)
    return context


def certificate_error(error):
    """Return safe structured certificate evidence, or None for other errors."""
    seen = set()
    pending = [error]
    while pending and len(seen) < 12:
        current = pending.pop(0)
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            code = getattr(current, 'verify_code', None)
            return {
                'category': 'tls_certificate_error',
                'verify_code': code if isinstance(code, int) else None,
                'message': ('HTTPS certificate verification failed. Check the computer clock and '
                            'the portable certificate bundle; the site may also have an invalid '
                            'certificate. Certificate verification remains enabled.'),
                'retry_after_seconds': 30,
            }
        if isinstance(current, urllib.error.URLError):
            pending.append(current.reason)
        pending.extend((current.__cause__, current.__context__))
    return None
