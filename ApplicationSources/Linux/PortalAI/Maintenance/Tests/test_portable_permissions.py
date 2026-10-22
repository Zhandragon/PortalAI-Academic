"""Real Windows restricted-token checks for public runtime transfer permissions."""
import ctypes
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'Tools'), str(ROOT/'ControlCenter')]
from portable_permissions import checked_tree, grant_runtime_read_execute, PUBLIC_TREES


def restricted_access(path, desired):
    """The second access check can use only the cross-machine AU SID."""
    from ctypes import wintypes as w
    adv = ctypes.WinDLL('advapi32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    class SidAttributes(ctypes.Structure):
        _fields_ = [('Sid', ctypes.c_void_p), ('Attributes', w.DWORD)]
    class Mapping(ctypes.Structure):
        _fields_ = [('Read', w.DWORD), ('Write', w.DWORD), ('Execute', w.DWORD), ('All', w.DWORD)]
    kernel.GetCurrentProcess.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    adv.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    adv.ConvertStringSidToSidW.argtypes = [w.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    adv.CreateRestrictedToken.argtypes = [w.HANDLE,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.c_void_p,
                                        w.DWORD,ctypes.POINTER(SidAttributes),ctypes.POINTER(w.HANDLE)]
    adv.DuplicateToken.argtypes = [w.HANDLE,ctypes.c_int,ctypes.POINTER(w.HANDLE)]
    adv.GetFileSecurityW.argtypes = [w.LPCWSTR,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD)]
    adv.AccessCheck.argtypes = [ctypes.c_void_p,w.HANDLE,w.DWORD,ctypes.POINTER(Mapping),ctypes.c_void_p,
                               ctypes.POINTER(w.DWORD),ctypes.POINTER(w.DWORD),ctypes.POINTER(w.BOOL)]
    handles = []; sid = ctypes.c_void_p()
    def checked(ok):
        if not ok: raise ctypes.WinError(ctypes.get_last_error())
    try:
        token=w.HANDLE();checked(adv.OpenProcessToken(kernel.GetCurrentProcess(),0x000a,ctypes.byref(token)));handles.append(token)
        checked(adv.ConvertStringSidToSidW('S-1-5-11',ctypes.byref(sid)))
        only_au=SidAttributes(sid,0);restricted=w.HANDLE()
        checked(adv.CreateRestrictedToken(token,1,0,None,0,None,1,ctypes.byref(only_au),ctypes.byref(restricted)));handles.append(restricted)
        impersonation=w.HANDLE();checked(adv.DuplicateToken(restricted,2,ctypes.byref(impersonation)));handles.append(impersonation)
        size=w.DWORD();adv.GetFileSecurityW(str(path),7,None,0,ctypes.byref(size))
        descriptor=ctypes.create_string_buffer(size.value)
        checked(adv.GetFileSecurityW(str(path),7,descriptor,size,ctypes.byref(size)))
        mapping=Mapping(0x120089,0x120116,0x1200a0,0x1f01ff)
        privileges=ctypes.create_string_buffer(4096);length=w.DWORD(len(privileges));granted=w.DWORD();status=w.BOOL()
        checked(adv.AccessCheck(descriptor,impersonation,desired,ctypes.byref(mapping),privileges,
                                ctypes.byref(length),ctypes.byref(granted),ctypes.byref(status)))
        return bool(status.value)
    finally:
        for handle in reversed(handles): kernel.CloseHandle(handle)
        if sid.value: kernel.LocalFree(sid)


class RuntimeBoundaryTests(unittest.TestCase):
    def test_private_and_unreviewed_directories_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for relative in ('Private/Users/x', 'Runtime/AccountPython/packages-preserved-old', 'Runtime/Unknown/packages',
                             'Runtime/StableDiffusion', 'Runtime/StableDiffusion/windows-cpu-preserved'):
                directory=root/relative;directory.mkdir(parents=True)
                with self.subTest(relative=relative), self.assertRaises(ValueError): checked_tree(root,directory)

    def test_hardlinks_are_refused_before_acl_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stage=root/'Runtime/AccountPython/packages-stage';stage.mkdir(parents=True)
            source=root/'private-example';source.write_bytes(b'unchanged');os.link(source,stage/'linked')
            with self.assertRaises(ValueError):checked_tree(root,stage)
            self.assertEqual(source.read_bytes(),b'unchanged')

    @unittest.skipUnless(os.name=='nt','Windows ACL access check')
    def test_cross_machine_read_execute_without_package_write_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stage=root/'Runtime/AccountPython/packages-stage';stage.mkdir(parents=True)
            file=stage/'library.py';file.write_bytes(b'public fixture')
            self.assertFalse(restricted_access(file,0x21))
            result=grant_runtime_read_execute(root,stage)
            self.assertTrue(result['changed'])
            self.assertTrue(restricted_access(file,0x21))
            self.assertFalse(restricted_access(file,0x2))
            self.assertTrue(restricted_access(stage,0x21))

    def test_preflight_uses_no_account_sessions_and_redacts_failure(self):
        from account_runtime import preflight, AccountRuntimeUnavailable
        with patch('local_accounts.LocalAccounts',side_effect=AssertionError('no profile access')):
            self.assertTrue(preflight()['ready'])
        with patch('local_accounts._crypto',side_effect=PermissionError('secret path or password')):
            with self.assertRaises(AccountRuntimeUnavailable) as caught: preflight()
        self.assertNotIn('secret path',str(caught.exception))
        self.assertIn('not a rejected password',str(caught.exception))

    @unittest.skipUnless(os.name=='nt','Windows ACL access check')
    def test_backend_stage_retains_portable_read_access_after_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stage=root/'LLM/backends/windows-vulkan-stage';stage.mkdir(parents=True)
            (stage/'llama-server.exe').write_bytes(b'public fixture')
            grant_runtime_read_execute(root,stage)
            active=stage.with_name('windows-vulkan');stage.rename(active)
            self.assertTrue(restricted_access(active/'llama-server.exe',0x21))
            self.assertFalse(restricted_access(active/'llama-server.exe',0x2))
            with self.assertRaises(ValueError):grant_runtime_read_execute(root,active)

    @unittest.skipUnless(os.name=='nt','Windows ACL access check')
    def test_foundation_import_does_not_publish_owner_only_temporary_acl(self):
        import hashlib
        import io
        import zipfile
        import import_foundation_assets as importer
        for relative, name, asset_id in (
                ('LLM/backends/windows-cpu', 'llama-server.exe', 'windows-cpu'),
                ('Runtime/StableDiffusion/windows-cpu', 'sd-cli.exe', 'sdcpp-windows-cpu'),
                ('Runtime/StableDiffusion/windows-vulkan', 'sd-cli.exe', 'sdcpp-windows-vulkan')):
            with self.subTest(runtime=relative), tempfile.TemporaryDirectory() as tmp:
                archive=io.BytesIO()
                with zipfile.ZipFile(archive,'w') as z:z.writestr(name,b'public fixture')
                payload=archive.getvalue()
                asset={'id':asset_id,'dest':relative,'archive':'zip','payload':'.',
                       'url':'https://example.invalid/fixture.zip','size':len(payload),
                       'sha256':hashlib.sha256(payload).hexdigest()}
                root=Path(tmp)
                with patch.object(importer,'require_space'), \
                     patch.object(importer.urllib.request,'urlopen',return_value=io.BytesIO(payload)):
                    result=importer.install(asset,root)
                self.assertEqual(result['status'],'installed-verified')
                exe=root/asset['dest']/name
                self.assertEqual(exe.read_bytes(),b'public fixture')
                self.assertTrue(restricted_access(exe,0x21))
                self.assertFalse(restricted_access(exe,0x2))

    def test_workspace_error_does_not_echo_sensitive_exception(self):
        from account_ui import workspace_failure_message
        error=FileNotFoundError(2,'secret-password','private-document-name')
        message=workspace_failure_message(error)
        self.assertIn('Password accepted',message)
        self.assertIn('OS error 2',message)
        self.assertNotIn('secret-password',message)
        self.assertNotIn('private-document-name',message)

    @unittest.skipUnless(os.name=='nt','Windows ACL access check')
    def test_every_reviewed_public_stage_has_cross_machine_access(self):
        from audit_portable_permissions import PortableAccess
        probe=PortableAccess()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                for relative in sorted(PUBLIC_TREES):
                    with self.subTest(tree=relative):
                        active=root/relative;stage=active.with_name(active.name+'-stage')
                        stage.mkdir(parents=True);file=stage/'fixture.dat';file.write_bytes(b'public')
                        self.assertFalse(probe.allows(file))
                        grant_runtime_read_execute(root,stage)
                        stage.rename(active)
                        self.assertTrue(probe.allows(active/'fixture.dat'))
                        self.assertFalse(probe.allows(active/'fixture.dat',0x2))
        finally:probe.close()

    @unittest.skipUnless(os.name=='nt','Windows ACL access check')
    def test_protected_individual_pip_files_get_explicit_portable_access(self):
        import subprocess
        from audit_portable_permissions import PortableAccess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stage=root/'Runtime/AccountPython/packages-stage';stage.mkdir(parents=True)
            file=stage/'protected.py';file.write_bytes(b'public')
            subprocess.run(['icacls',str(file),'/inheritance:r','/grant','*S-1-3-4:F'],
                           check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            probe=PortableAccess()
            try:
                self.assertFalse(probe.allows(file))
                grant_runtime_read_execute(root,stage)
                self.assertTrue(probe.allows(file))
                self.assertFalse(probe.allows(file,0x2))
            finally:probe.close()

    def test_unreviewed_stage_and_preserved_names_do_not_expand_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for relative in ('Private/Users-stage','Runtime/LinuxPackages/unknown-stage',
                             'Runtime/LinuxPython-inaccessible-old','Runtime/LinuxTorch/cpu-stage-nothex'):
                directory=root/relative;directory.mkdir(parents=True)
                with self.subTest(tree=relative),self.assertRaises(ValueError):checked_tree(root,directory)

    def test_public_repair_refuses_modified_wheel_before_install_or_rename(self):
        import repair_public_runtimes as repair
        import profile_shutdown
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);receipt=root/'Maintenance/Imports/amd-audio-lock.json';receipt.parent.mkdir(parents=True)
            lock=root/'Private/profile-runtime.lock';lock.parent.mkdir();lock.write_bytes(b'0')
            wheel=root/'Cache/fixture.whl';wheel.parent.mkdir();wheel.write_bytes(b'changed')
            receipt.write_text(json.dumps({'assets':[{'wheel':'Cache/fixture.whl','bytes':7,'sha256':'0'*64}]}))
            with patch.object(profile_shutdown,'_snapshot',return_value={}), \
                 patch.object(repair.subprocess,'run',side_effect=AssertionError('must not install')):
                with self.assertRaisesRegex(ValueError,'differs from pinned'):repair.repair('amd-audio',root)

    def test_public_repair_requires_closed_controller_before_touching_runtime(self):
        import repair_public_runtimes as repair
        import profile_shutdown
        from mission_runner import process_lock
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);lock=root/'Private/profile-runtime.lock';lock.parent.mkdir();lock.write_bytes(b'0')
            with patch.object(profile_shutdown,'_snapshot',return_value={}), \
                 patch.object(repair,'_repair_stopped',side_effect=AssertionError('must not repair')):
                with patch.object(profile_shutdown,'_select',return_value={123:{}}):
                    with self.assertRaisesRegex(RuntimeError,'Close PortalAI'):repair.repair('amd-audio',root)
                with process_lock(lock):
                    with self.assertRaises(RuntimeError):repair.repair('amd-audio',root)

    def test_offline_repair_rejects_traversal_and_changed_cached_wheel(self):
        from repair_account_runtime import verified_assets
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);receipt=root/'Maintenance/Imports/account-runtime-lock.json';receipt.parent.mkdir(parents=True)
            row={'name':'cryptography','wheel':'../outside.whl','sha256':'0'*64,'bytes':1}
            receipt.write_text(json.dumps({'assets':[row]}))
            with self.assertRaises(ValueError):verified_assets(root)
            row['wheel']='Cache/account-runtime-wheelhouse/example.whl'
            wheel=root/row['wheel'];wheel.parent.mkdir(parents=True);wheel.write_bytes(b'x')
            receipt.write_text(json.dumps({'assets':[row]}))
            with self.assertRaisesRegex(ValueError,'verified receipt'):verified_assets(root)


if __name__=='__main__':unittest.main()
