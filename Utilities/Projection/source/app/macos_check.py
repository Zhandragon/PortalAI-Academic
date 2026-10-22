"""Read-only Mac import/runtime probe; no accounts, HA traffic, or capture."""
import sys
from pathlib import Path
MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'app'))
from host_runtime import package_paths,mac_arch
sys.path[:0]=package_paths()

def main():
    import json,platform,ssl,tkinter
    import cryptography,psutil,objc,Quartz,ScreenCaptureKit
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    key=AESGCM.generate_key(bit_length=256);cipher=AESGCM(key)
    assert cipher.decrypt(b'0'*12,cipher.encrypt(b'0'*12,b'probe',None),None)==b'probe'
    assert hasattr(ScreenCaptureKit,'SCScreenshotManager')
    assert hasattr(ScreenCaptureKit.SCStreamConfiguration,'setIgnoreShadowsSingleWindow_')
    assert ssl.create_default_context(cafile=str(MODULE/'Runtime/cacert.pem')).verify_mode==ssl.CERT_REQUIRED
    print(json.dumps({'architecture':mac_arch(),'macOS':platform.mac_ver()[0],
        'python':platform.python_version(),'tk':tkinter.Tcl().eval('info patchlevel'),
        'screen_recording_granted':bool(Quartz.CGPreflightScreenCaptureAccess()),
        'native_execution':True,'capture_tested':False,'HA_tested':False},indent=2))

if __name__=='__main__':main()
