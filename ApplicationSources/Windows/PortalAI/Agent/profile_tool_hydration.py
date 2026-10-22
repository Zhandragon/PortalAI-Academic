"""Prepare ordinary filesystem paths before unmanaged media/science libraries."""
from __future__ import annotations


def prepare_tool_files(root, command, *, operation=None, action=None):
    """Inspection/cancellation stays cheap; jobs preserve old file collisions.

    Native programs cannot ask the profile broker for missing paths. Restore
    their working input/output trees before they inspect directories or choose
    an unused output filename. Archive/history trees stay lazy unless selected.
    """
    command=str(command or '').strip().lower()
    if command in {'help','status','version','cancel','capabilities','route','preview','media-info'}:
        return
    if command == 'science' and str(operation or 'help').strip().lower() in {'help','status','capabilities'}:
        return
    if command == 'service' and str(action or '').strip().lower() in {'status','stop','list','wait'}:
        return
    from profile_hydration import materialize
    for relative in ('Outputs', 'User Folder'):
        materialize(root, relative, recursive=True)
