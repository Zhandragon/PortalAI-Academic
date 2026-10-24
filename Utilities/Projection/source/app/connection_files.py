"""Narrow filesystem operations for saved projection connections."""
from pathlib import Path
import re


def delete_saved_connection(connections_dir, connection_path):
    """Delete one direct-child encrypted connection and its pairing export.

    The encrypted file is the authority. The public pairing export is optional;
    failure to remove it is reported separately after the encrypted file is gone.
    No directory traversal or recursive cleanup is performed.
    """
    directory = Path(connections_dir)
    selected = Path(connection_path)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Connections folder is unavailable or linked')
    directory = directory.resolve(strict=True)
    if selected.suffix != '.enc' or not re.fullmatch(r'[0-9a-f]{32}', selected.stem):
        raise ValueError('Select a saved encrypted connection')
    if selected.parent.resolve(strict=True) != directory:
        raise ValueError('Connection must be directly inside the Connections folder')
    if selected.is_symlink() or not selected.is_file():
        raise ValueError('Connection is missing, linked or not a regular file')

    pairing = directory / (selected.stem + '.public-pairing.json')
    if pairing.exists() and not pairing.is_file() and not pairing.is_symlink():
        raise ValueError('Pairing export is not a regular file')

    # Remove the encrypted private key first. If this fails, leave the public
    # export and the live UI state untouched.
    selected.unlink()
    try:
        pairing.unlink()
        pairing_removed = True
    except FileNotFoundError:
        pairing_removed = False
    except OSError as exc:
        return {'connection_removed': True, 'pairing_removed': False,
                'pairing_error': str(exc)}
    return {'connection_removed': True, 'pairing_removed': pairing_removed,
            'pairing_error': None}
