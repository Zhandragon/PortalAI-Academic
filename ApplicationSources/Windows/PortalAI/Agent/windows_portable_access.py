"""Read-only Windows access checks independent of machine-specific owner SIDs."""
import os
import ctypes
from ctypes import wintypes as w


class PortableAccess:
    def __init__(self):
        if os.name!='nt':raise RuntimeError('This audit checks Windows NTFS permissions')
        self.adv=ctypes.WinDLL('advapi32',use_last_error=True)
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        class SidAttributes(ctypes.Structure):
            _fields_=[('Sid',ctypes.c_void_p),('Attributes',w.DWORD)]
        class Mapping(ctypes.Structure):
            _fields_=[('Read',w.DWORD),('Write',w.DWORD),('Execute',w.DWORD),('All',w.DWORD)]
        self.mapping=Mapping(0x120089,0x120116,0x1200a0,0x1f01ff)
        self.kernel.GetCurrentProcess.restype=w.HANDLE
        self.kernel.CloseHandle.argtypes=[w.HANDLE]
        self.kernel.LocalFree.argtypes=[ctypes.c_void_p]
        self.adv.OpenProcessToken.argtypes=[w.HANDLE,w.DWORD,ctypes.POINTER(w.HANDLE)]
        self.adv.ConvertStringSidToSidW.argtypes=[w.LPCWSTR,ctypes.POINTER(ctypes.c_void_p)]
        self.adv.CreateRestrictedToken.argtypes=[w.HANDLE,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.POINTER(SidAttributes),ctypes.POINTER(w.HANDLE)]
        self.adv.DuplicateToken.argtypes=[w.HANDLE,ctypes.c_int,ctypes.POINTER(w.HANDLE)]
        self.adv.GetFileSecurityW.argtypes=[w.LPCWSTR,w.DWORD,ctypes.c_void_p,w.DWORD,ctypes.POINTER(w.DWORD)]
        self.adv.AccessCheck.argtypes=[ctypes.c_void_p,w.HANDLE,w.DWORD,ctypes.POINTER(Mapping),ctypes.c_void_p,ctypes.POINTER(w.DWORD),ctypes.POINTER(w.DWORD),ctypes.POINTER(w.BOOL)]
        self.handles=[];self.sid=ctypes.c_void_p();self.cache={}
        try:
            token=w.HANDLE();self.checked(self.adv.OpenProcessToken(self.kernel.GetCurrentProcess(),0xa,ctypes.byref(token)));self.handles.append(token)
            self.checked(self.adv.ConvertStringSidToSidW('S-1-5-11',ctypes.byref(self.sid)))
            restricted=w.HANDLE();sid=SidAttributes(self.sid,0)
            self.checked(self.adv.CreateRestrictedToken(token,1,0,None,0,None,1,ctypes.byref(sid),ctypes.byref(restricted)));self.handles.append(restricted)
            self.token=w.HANDLE();self.checked(self.adv.DuplicateToken(restricted,2,ctypes.byref(self.token)));self.handles.append(self.token)
        except BaseException:self.close();raise

    @staticmethod
    def checked(ok):
        if not ok:raise ctypes.WinError(ctypes.get_last_error())

    def allows(self,path,desired=0x1200a9):
        from portable_fs import native_path
        size=w.DWORD()
        self.adv.GetFileSecurityW(native_path(path),7,None,0,ctypes.byref(size))
        if not size.value:raise ctypes.WinError(ctypes.get_last_error())
        descriptor=ctypes.create_string_buffer(size.value)
        self.checked(self.adv.GetFileSecurityW(native_path(path),7,descriptor,size,ctypes.byref(size)))
        key=(descriptor.raw,desired)
        if key not in self.cache:
            privileges=ctypes.create_string_buffer(4096);length=w.DWORD(len(privileges));granted=w.DWORD();status=w.BOOL()
            self.checked(self.adv.AccessCheck(descriptor,self.token,desired,ctypes.byref(self.mapping),privileges,ctypes.byref(length),ctypes.byref(granted),ctypes.byref(status)))
            self.cache[key]=bool(status.value)
        return self.cache[key]

    def close(self):
        for handle in reversed(self.handles):self.kernel.CloseHandle(handle)
        self.handles=[]
        if self.sid.value:self.kernel.LocalFree(self.sid);self.sid=ctypes.c_void_p()

