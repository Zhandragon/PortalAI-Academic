"""Trusted-session authorization for shared settings and host mission controls.

This is an application request boundary; it is not OS isolation. Session roles
come from the authenticated in-process registry, never environment labels or a
GUI-provided role string. Legacy installations preserve their existing behavior.
"""
from pathlib import Path


def require_admin(root, session=None):
    from profile_paths import enabled, capture
    from local_accounts import Session
    root = Path(root).resolve()
    if not enabled(root): return None
    session = session() if callable(session) else session
    if not isinstance(session, Session):
        raise PermissionError('Sign in as an administrator to manage shared settings or persistent missions.')
    backend = session._store()
    if backend is None or backend.root != root:
        raise PermissionError('This authentication belongs to another installation.')
    with backend._lock():
        backend._validate(session, backend._read(), admin=True)
    identity = capture(root)
    if identity is None or identity[0] != session.user_id:
        raise PermissionError('The administrator profile is not the active account.')
    return session


def can_admin(root, session=None):
    try:
        require_admin(root, session)
        return True
    except (OSError, ValueError, RuntimeError, PermissionError):
        return False


def require_user(root, session=None):
    from profile_paths import enabled, capture
    from local_accounts import Session
    root = Path(root).resolve()
    if not enabled(root): return None
    session = session() if callable(session) else session
    if not isinstance(session, Session):
        raise PermissionError('Sign in to save your personal settings.')
    backend = session._store()
    if backend is None or backend.root != root:
        raise PermissionError('This authentication belongs to another installation.')
    backend.validate_session(session)
    identity = capture(root)
    if identity is None or identity[0] != session.user_id:
        raise PermissionError('This profile is not the active account.')
    return session


def can_user(root, session=None):
    try:
        require_user(root, session)
        return True
    except (OSError, ValueError, RuntimeError, PermissionError):
        return False
