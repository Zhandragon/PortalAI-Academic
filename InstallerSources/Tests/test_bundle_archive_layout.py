"""Prevent Windows default-folder extraction failures and runtime stripping."""
from pathlib import Path
import importlib.util, unittest

source=Path(__file__).resolve().parents[2]/'tools/build_welcome_bundles.py'
spec=importlib.util.spec_from_file_location('bundle_builder',source)
builder=importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)

class ArchiveLayout(unittest.TestCase):
    def test_reported_pyobjc_debug_path_is_excluded(self):
        path='PortalAI-Projection/Runtime/MacPackages-x86_64/PyObjCTest/testoutputinitializer.cpython-312-darwin.so.dSYM/Contents/Resources/Relocations/aarch64/testoutputinitializer.cpython-312-darwin.so.yml'
        self.assertTrue(builder.mac_development_file(path))
        with self.assertRaises(ValueError):
            builder.windows_path_report(['Utilities/Mac/'+path])

    def test_mac_runtime_extensions_metadata_and_licenses_remain(self):
        for arch in ('arm64','x86_64'):
            for path in ('objc/_objc.cpython-312-darwin.so','ScreenCaptureKit/__init__.py',
                         'pyobjc_core-12.2.2.dist-info/RECORD','pyobjc_core-12.2.2.dist-info/licenses/LICENSE.txt'):
                self.assertFalse(builder.mac_development_file(f'PortalAI-Projection/Runtime/MacPackages-{arch}/'+path))

    def test_filter_is_limited_to_mac_runtime_development_files(self):
        self.assertTrue(builder.mac_development_file('PortalAI-Projection/Runtime/MacPackages-arm64/PyObjCTest/test.py'))
        self.assertTrue(builder.mac_development_file('PortalAI-Projection/Runtime/MacPackages-arm64/objc/_objc.so.dSYM/Contents/Info.plist'))
        self.assertFalse(builder.mac_development_file('PortalAI-Projection/app/PyObjCTest/test.py'))
        self.assertFalse(builder.mac_development_file('PortalAI-Projection/Runtime/Windows/PyObjCTest/test.py'))

    def test_file_limit_includes_destination_and_terminating_null(self):
        self.assertEqual(builder.windows_path_report(['x'*138])['max_full_path_characters'],259)
        with self.assertRaises(ValueError):builder.windows_path_report(['x'*139])

    def test_directory_limit_is_checked_separately(self):
        builder.windows_path_report(['x'*126+'/a'])
        with self.assertRaises(ValueError):builder.windows_path_report(['x'*127+'/a'])

    def test_windows_counts_utf16_code_units(self):
        self.assertEqual(builder.windows_path_report(['\U0001f600'*69])['max_full_path_characters'],259)
        with self.assertRaises(ValueError):builder.windows_path_report(['\U0001f600'*70])

if __name__=='__main__':unittest.main()
