"""One-time account setup for an explicitly reviewed, registry-free copy.

Ordinary missing/corrupt registries still require recovery. A repair ticket
binds setup to an exact legacy inventory and verified current source copies.
Migration uses the existing encrypted-backup, verification and sealing path.
"""
import hmac
import json
from pathlib import Path
import re
import sys

TICKET = 'Maintenance/Repair/initial-account-setup.json'
KIND = 'reviewed-initial-account-setup-v1'


def _paths(root, ticket):
    from profile_paths import _contained, _relative
    root = Path(root).resolve()
    backup = _contained(root, root / _relative(ticket['source_backup']))
    mirror = _contained(root.parent, root.parent / _relative(ticket['source_mirror']))
    recovery = _contained(root.parent, root.parent / _relative(ticket['recovery_directory']))
    if not backup.is_relative_to(root / 'Maintenance/Patches'):
        raise ValueError('Source recovery must use the public patch directory')
    for path in (mirror, recovery):
        if path == root.parent or path.is_relative_to(root) or not path.is_dir():
            raise ValueError('External recovery directory is missing or invalid')
    return backup, mirror, recovery


def _read(root):
    from profile_paths import _contained
    root = Path(root).resolve()
    path = _contained(root, root / TICKET)
    if not path.exists():
        return None
    if path.stat().st_size > 16384 or path.stat().st_nlink != 1:
        raise ValueError('Invalid first-account repair ticket')
    ticket = json.loads(path.read_text(encoding='utf-8'))
    if (ticket.get('kind') != KIND or ticket.get('phase') not in ('ready', 'started', 'complete')
            or not re.fullmatch('[a-f0-9]{64}', ticket.get('inventory_digest', ''))):
        raise ValueError('Invalid first-account repair ticket')
    _paths(root, ticket)
    return ticket


def _eligible(root, backend, ticket):
    if ticket['phase'] == 'complete':
        return None
    status = backend.status()
    if ticket['phase'] == 'started' and status['state'] == 'locked':
        owner = ticket.get('owner')
        if any(row.get('role') == 'admin' and row.get('username') == owner
               for row in status.get('users', [])):
            return {'mode': 'resume', 'owner': owner}
        return None
    # Never offer new initialization around existing keys or lifecycle evidence.
    from profile_paths import enabled
    if enabled(root):
        return None
    inventory = backend.private_inventory()
    if not hmac.compare_digest(ticket['inventory_digest'], inventory['digest']):
        return None
    return {'mode': 'create', 'files': len(inventory['files']), 'bytes': inventory['bytes']}


def inspect(root, backend):
    """Read-only UI availability. Failure leaves the ordinary recovery gate."""
    try:
        ticket = _read(root)
        return _eligible(Path(root).resolve(), backend, ticket) if ticket else None
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return None


def provision_reviewed(root, username, password):
    from local_accounts import LocalAccounts
    from runtime_policy import atomic_json
    root = Path(root).resolve()
    ticket = _read(root)
    backend = LocalAccounts(root)
    eligibility = _eligible(root, backend, ticket) if ticket else None
    if eligibility is None:
        raise RuntimeError('The reviewed setup inventory is no longer current')
    if eligibility['mode'] == 'resume' and username != eligibility['owner']:
        raise ValueError('Use the administrator chosen when setup began')
    backup, mirror, recovery = _paths(root, ticket)
    tools = str(root / 'Tools')
    if tools not in sys.path:
        sys.path.insert(0, tools)
    from initialize_profiles import provision, verify_source_recovery
    verify_source_recovery(root, backup, mirror)
    # Mark the attempt before initialization, so an interrupted migration can
    # resume only with the newly created administrator's actual password.
    ticket.update(phase='started', owner=username)
    atomic_json(root / TICKET, ticket)
    result = provision(root, username, password,
                       resume=eligibility['mode'] == 'resume',
                       recovery_directory=recovery,
                       expected_inventory_digest=ticket['inventory_digest'])
    if result.get('verified') is not True or result.get('external_recovery_verified') is not True:
        raise RuntimeError('Initial account migration did not verify')
    ticket['phase'] = 'complete'
    atomic_json(root / TICKET, ticket)
    return result
