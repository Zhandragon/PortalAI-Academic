"""Install isolated wallet-signing/vault libraries from a pinned PyPI resolution."""
from import_amd_audio import main

if __name__=='__main__':
    main(prefix='account-runtime',pins={'eth_account':'0.14.0','cryptography':'50.0.2'},
         relative_dest='Runtime/AccountPython/packages',exact=False)
