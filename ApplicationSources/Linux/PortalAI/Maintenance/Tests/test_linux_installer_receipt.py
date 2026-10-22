"""Receipt lookup follows the clean release without hardcoding an obsolete revision."""
from pathlib import Path
import sys, tempfile, unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'Tools'))
import install_linux_clean as installer

class LinuxReceiptTests(unittest.TestCase):
    def test_current_receipt_is_used_for_backend_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);imports=root/'Maintenance/Imports';imports.mkdir(parents=True)
            receipt=imports/'linux-clean-installer-r5.json';receipt.write_text('{}')
            with patch.object(installer,'ROOT',root),patch.object(installer,'verify_rows',return_value=1) as verify:
                installer.verify_installed_layers()
            self.assertEqual(verify.call_args_list[1].args[1],receipt)

    def test_missing_or_multiple_receipts_fail_instead_of_guessing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);imports=root/'Maintenance/Imports';imports.mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError,'found 0'):installer.clean_installer_receipt(root)
            for n in (2,5):(imports/f'linux-clean-installer-r{n}.json').write_text('{}')
            with self.assertRaisesRegex(RuntimeError,'found 2'):installer.clean_installer_receipt(root)

    def test_older_complete_install_can_verify_its_own_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);imports=root/'Maintenance/Imports';imports.mkdir(parents=True)
            receipt=imports/'linux-clean-installer-r2.json';receipt.write_text('{}')
            self.assertEqual(installer.clean_installer_receipt(root),receipt)

if __name__=='__main__':unittest.main()
