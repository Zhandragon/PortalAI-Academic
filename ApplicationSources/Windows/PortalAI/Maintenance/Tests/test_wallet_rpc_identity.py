"""The public RPC receives an honest product identity and retains redirect guards."""
import unittest
from unittest.mock import Mock, patch
import mission_accounts

class RpcIdentityTests(unittest.TestCase):
    def test_rpc_has_product_identity_without_secrets(self):
        response=Mock();response.read.return_value=b'{"jsonrpc":"2.0","id":1,"result":"0x1"}'
        opener=Mock();opener.open.return_value.__enter__=Mock(return_value=response)
        opener.open.return_value.__exit__=Mock(return_value=False)
        with patch.object(mission_accounts.urllib.request,'build_opener',return_value=opener) as build:
            value=mission_accounts.Accounts.rpc(None,{'rpc_url':'https://example.test/rpc'},'eth_chainId',[])
        self.assertEqual(value,'0x1')
        request=opener.open.call_args.args[0]
        self.assertEqual(request.get_header('User-agent'),'PortalAI/1.0')
        self.assertEqual(request.get_header('Accept'),'application/json')
        self.assertNotIn('Authorization',request.headers)
        build.assert_called_once_with(mission_accounts.NoRedirect)

if __name__=='__main__':unittest.main()
