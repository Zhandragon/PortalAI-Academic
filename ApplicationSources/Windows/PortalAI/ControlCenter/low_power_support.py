"""Optional general task scaffolding for the actual running 1.7B/4B model.

No task solutions, writes, permission grants or larger budgets. Missing public
source paths may trigger a bounded filename lookup within the requested tool.
Retrieved text is evidence, never policy; suggestions do not execute a retry.
"""
import json
import re
from pathlib import PurePosixPath


def missing_source_hint(runtime, identifier, requested):
    """Suggest observed public filenames after an authorized path lookup fails."""
    if not supported_model(identifier) or not isinstance(requested,str):return None
    from source_map import PUBLIC, source_map
    relative=PurePosixPath(requested.replace('\\','/'))
    if (relative.is_absolute() or '..' in relative.parts or ':' in requested
            or not relative.parts or relative.parts[0] not in PUBLIC
            or relative.suffix not in ('.py','.txt','.md') or len(relative.name)>200):return None
    if runtime._account_role()!='admin':raise PermissionError('Source suggestions require administrator access')
    epoch=getattr(runtime,'_cancel_epoch',None)
    found=json.loads(source_map(runtime,query=relative.name,limit=60))
    exact=[item for item in found['items'] if PurePosixPath(item['path']).name.casefold()==relative.name.casefold()]
    if runtime._account_role()!='admin':raise PermissionError('Administrator access ended')
    if epoch!=getattr(runtime,'_cancel_epoch',None):raise RuntimeError('Source lookup cancelled')
    return json.dumps({'ok':False,'error':'Requested public source path was not found','requested_path':relative.as_posix(),
        'support_kind':'public_source_path_suggestions','candidates':exact[:8],
        'scan_truncated':bool(found['scan_truncated'] or found['next_offset'] is not None or len(exact)>8),
        'public_root_roles':{'Agent':'Tool implementations and runtime/backend adapters','ControlCenter':'GUI, chat and tool interfaces',
                             'Tools':'Installation, recovery and maintenance commands','Documentation':'Public manuals'},
        'automatic_retry':False,'note':'Observed filename matches only; no suggested file was opened or executed. Choose a candidate and retry the lookup, then inspect its contents before editing.'},ensure_ascii=True)


def supported_model(identifier):
    value = str(identifier or '').replace('\\', '/').rsplit('/', 1)[-1].lower()
    return bool(re.search(r'(?:^|[-_ ])(?:1[._]7b|4b)(?:$|[-_. ])', value)
                or re.fullmatch(r'qwen(?:1[._]7|4)(?:[-_]q\d.*)?', value))


def guidance(identifier, messages=()):
    if not supported_model(identifier): return ''
    note = (
        'Optional low-power model support is active for this running 1.7B/4B model. '
        'Keep a short task checklist: required behavior, evidence to inspect, smallest change, verification. '
        'Separate observed facts from assumptions; test an assumption before relying on it. '
        'For coding, inspect_environment gives the real installation and workspace. '
        'application_root is a returned field, not a literal folder name; source tools take paths relative to its value. '
        'Use source_map with a filename query across public roots, then source_map(path=the Python file) for symbols and offsets. '
        'Missing public-source paths may return filename suggestions; inspect a candidate before using it. '
        'source_search matches literal code text or exact symbols; a prose description of desired behavior is not a semantic search. '
        'Do not repeatedly guess function names in one file after empty searches; widen the search or follow imports/callers. '
        'Read the complete relevant symbol using its offsets, not repeated first pages. '
        'Reproduce the behavior, make a focused edit, then run the actual test command and check its exit status. '
        'After any further edit, previous passing tests are stale. A write receipt or a proposed command is not a test result. '
        'For research, use direct read for a known URL, site_search for a domain, catalog_search for research records, '
        'discover for site search forms and linked files, data for structured records, and browser tools for rendered pages. '
        'Follow available pagination and read original documents. Metadata and search snippets do not establish media contents. '
        'Fetch tool help for unfamiliar arguments. Keep a concise checkpoint of verified facts, paths and remaining checks when context fills. '
        'This support does not change account permissions, Stop, resource limits or safeguards against repeating writes.'
    )
    misses = 0
    for row in list(messages or ())[-24:]:
        if not isinstance(row, dict) or row.get('role') != 'tool' or row.get('name') != 'source_search': continue
        try: result = json.loads(row.get('content', ''))
        except (ValueError, TypeError): continue
        if isinstance(result, dict) and result.get('matches') == []: misses += 1
    if misses >= 2:
        note += ' Host observation: recent source lookups returned no matches more than once. Map candidate files and symbols or broaden the path before guessing another name.'
    return note
