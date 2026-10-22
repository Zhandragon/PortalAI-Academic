"""Run bundled pip with a narrowly scoped Windows RECORD path correction.

Pip 26.2.1 joins relocated script RECORD paths (../../bin/name) to its
temporary library. Windows extended paths require those dot segments to be
normalized before file I/O. Original wheel containment and hash checks, script
rewriting, installed RECORD generation and final target relocation remain pip's.
No installed pip files or machine policies are modified.
"""
import contextlib
import inspect
import os
import sys


@contextlib.contextmanager
def normalized_record_paths(wheel, version, *, windows=None):
    if windows is None:
        windows = os.name == 'nt'
    if not windows:
        yield
        return
    if version != '26.2.1':
        raise RuntimeError('Portable repair requires reviewed bundled pip 26.2.1')
    original = wheel._record_to_fs_path
    if tuple(inspect.signature(original).parameters) != ('record_path', 'lib_dir'):
        raise RuntimeError('Bundled pip RECORD helper has changed; review required')

    def normalized(record_path, lib_dir):
        # This converts pip's already-validated installed RECORD location only.
        # It does not normalize or approve untrusted archive member names.
        return os.path.normpath(original(record_path, lib_dir))

    wheel._record_to_fs_path = normalized
    try:
        yield
    finally:
        wheel._record_to_fs_path = original


def main(argv=None):
    import pip
    from pip._internal.operations.install import wheel
    from pip._internal.cli.main import main as pip_main
    with normalized_record_paths(wheel, pip.__version__):
        return pip_main(sys.argv[1:] if argv is None else argv)


if __name__ == '__main__':
    raise SystemExit(main())
