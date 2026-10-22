"""Canonical application paths with Windows long-path I/O, without registry edits.

Strings and path comparisons retain normal drive/UNC spelling. Long OS paths
get the extended prefix; managed walks normalize their results again. This does not
authorize a path: callers must retain their containment/link/identity checks.
"""
import os
import pathlib
import re


def _canonical(value):
    value = os.fspath(value)
    if isinstance(value, bytes):
        raise TypeError('Portable paths require text')
    if value.startswith('\\\\?\\UNC\\'):
        return '\\\\' + value[8:]
    if value.startswith('\\\\?\\'):
        plain = value[4:]
        if not re.match(r'^[a-zA-Z]:[\\/]', plain):
            raise ValueError('Windows device namespaces are not portable file paths')
        return plain
    if value.startswith('\\\\.\\'):
        raise ValueError('Windows device namespaces are not portable file paths')
    return value


if os.name == 'nt':
    class Path(pathlib.WindowsPath):
        def __init__(self, *args):
            super().__init__(*(_canonical(value) for value in args))

        def __fspath__(self):
            text = str(self)
            if not self.is_absolute() or len(text.encode('utf-16-le')) < 480:
                return text
            if text.startswith('\\\\'):
                return '\\\\?\\UNC\\' + text[2:]
            return '\\\\?\\' + text
else:
    Path = pathlib.Path


def native_path(value):
    """Extend a whole Windows traversal, including descendants not yet visited."""
    path = Path(value)
    text = str(path)
    if os.name != 'nt' or not path.is_absolute():
        return text
    if text.startswith('\\\\'):
        return '\\\\?\\UNC\\' + text[2:]
    return '\\\\?\\' + text


def walk(value, **options):
    for folder, directories, files in os.walk(native_path(value), **options):
        yield _canonical(folder) if os.name == 'nt' else folder, directories, files


def raise_walk_error(error):
    """An unreadable subtree is not an empty subtree in a recovery inventory."""
    raise error
