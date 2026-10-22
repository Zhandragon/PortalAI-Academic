"""Exercise synthetic internal account panels on the bundled Linux Tk/Xvfb."""
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path('/portable')
sys.path[:0] = [str(ROOT/'Agent'), str(ROOT/'ControlCenter'),
               str(ROOT/'Runtime/LinuxPackages/gui'), str(ROOT/'Validation/Tests')]


def main():
    native = ROOT/'Runtime/LinuxSystem/rootfs'
    lib = native/'usr/lib'
    loader = lib/'x86_64-linux-gnu/ld-linux-x86-64.so.2'
    libraries = ':'.join(map(str, (lib/'x86_64-linux-gnu', lib)))
    log = ROOT/'Data/account-surface-xvfb.log'
    process = None
    try:
        with log.open('wb') as output:
            process = subprocess.Popen([
                str(loader), '--library-path', libraries, str(native/'usr/bin/Xvfb'),
                ':19', '-screen', '0', '1280x900x24', '-nolisten', 'tcp', '-ac',
                '-extension', 'GLX', '-fp', str(native/'usr/share/fonts/X11/misc'),
            ], stdin=subprocess.DEVNULL, stdout=output, stderr=output)
            os.environ['DISPLAY'] = ':19'
            os.environ['FONTCONFIG_PATH'] = str(native/'etc/fonts')
            import tkinter as tk
            deadline = time.monotonic() + 5
            while True:
                try:
                    app = tk.Tk()
                    app.destroy()
                    break
                except tk.TclError:
                    if process.poll() is not None or time.monotonic() >= deadline:
                        raise RuntimeError('Bundled Xvfb/Tk did not become ready: '+log.read_text(errors='replace'))
                    time.sleep(.1)
            suite = unittest.defaultTestLoader.discover(
                str(ROOT/'Validation/Tests'), pattern='test_account_presentation_tk.py')
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            if not result.wasSuccessful() or result.skipped or result.testsRun < 6:
                raise AssertionError({'tests': result.testsRun, 'skipped': len(result.skipped),
                                      'errors': len(result.errors), 'failures': len(result.failures)})
            print(f'Bundled Linux Tk: {result.testsRun} synthetic internal account panel checks passed, zero skips', flush=True)
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == '__main__':
    main()
