"""Public dependency preflight; never authenticates or opens a private profile."""
class AccountRuntimeUnavailable(RuntimeError):
    pass


def preflight():
    try:
        from local_accounts import _crypto
        aes, scrypt = _crypto()
        key = scrypt(salt=b'PortalAI-runtime!', length=32, n=1024, r=8, p=1).derive(b'public self-test')
        cipher = aes(key)
        nonce = b'PortalAItest!'
        if cipher.decrypt(nonce, cipher.encrypt(nonce, b'portable', b'check'), b'check') != b'portable':
            raise RuntimeError('Account runtime self-test failed')
    except Exception:
        raise AccountRuntimeUnavailable(
            'PortalAI cannot load its bundled account encryption support on this computer. '
            'This is a runtime installation or file-permission problem, not a rejected password. '
            'Close PortalAI and run Launchers/Repair_Account_Runtime.cmd from this drive. '
            'That offline repair uses verified bundled packages and preserves your accounts and encrypted files.'
        ) from None
    return {'ready': True, 'private_profiles_opened': False}
