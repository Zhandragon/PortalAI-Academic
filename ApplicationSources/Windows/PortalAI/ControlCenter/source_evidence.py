"""Preserve actionable source evidence in small model-context views.

Pure projection of saved receipts: no file reads, imports of inspected code,
permission decisions or tool dispatch. Exact transcript pages remain available.
"""
import json


def project_source(message, message_id, limit):
    name = message.get('name')
    if name not in ('source_map', 'source_search', 'inspect_environment'):
        return None
    try:
        row = json.loads(str(message.get('content') or ''))
    except (ValueError, TypeError, RecursionError):
        return None
    if not isinstance(row, dict):
        return None
    encode = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    base = {'kind': name, 'message_id': message_id, 'evidence_only': True,
            'view_compacted': True, 'exact': 'chat_history action=read'}
    if name == 'inspect_environment':
        if not isinstance(row.get('application_root'), str):
            return None
        result = dict(base)
        for key in ('os', 'shell', 'account_role', 'file_edit_allowed', 'application_root', 'python', 'shell_working_directory', 'evaluation_constraints'):
            if key in row:
                trial = {**result, key: row[key]}
                if len(encode(trial)) <= limit:
                    result = trial
        return encode(result) if len(encode(result)) <= limit else None
    if name == 'source_map':
        mode = row.get('mode')
        if mode not in ('files', 'ranked_files', 'python_outline', 'tool_entrypoint') or not isinstance(row.get('items'), list):
            return None
        key, items = 'items', row['items']
        base['mode'] = mode
        base['next_tool'] = 'read_file at listed character offsets' if mode == 'python_outline' else 'source_map with candidate path'
        # A compact projection still represents only one source_map page. Without
        # its cursor the model cannot discover symbols/files beyond that page.
        if type(row.get('total_items')) is int:
            base['total_items'] = row['total_items']
        if row.get('next_offset') is None or type(row.get('next_offset')) is int:
            if 'next_offset' in row:
                base['next_offset'] = row['next_offset']
        if type(row.get('next_offset')) is int:
            base['more_items'] = 'source_map with same path/query and offset=next_offset; history contains this page only'
        if mode in ('python_outline','tool_entrypoint'):
            base['path'] = row.get('path')
        if mode=='tool_entrypoint':
            base['tool']=row.get('tool')
            base['note']='Observed dispatch locations; static evidence, not execution.' if items else row.get('note','')[:160]
            if not items and isinstance(row.get('observed_tools'),list):
                base['observed_tools']=row['observed_tools'][:8]
    else:
        if not isinstance(row.get('matches'), list):
            return None
        mode = 'matches' if row['matches'] else 'suggestions'
        key = 'matches' if row['matches'] else 'suggested_files'
        items = row.get(key, [])
        if not isinstance(items, list):
            return None
        if mode == 'suggestions':
            base.update(matches=[], note='No literal matches. Candidates are lexical suggestions, not a diagnosis.')
        else:
            base['next_tool'] = 'read_file with the listed path and character offset'
    if 'scan_truncated' in row:
        base['scan_truncated'] = row['scan_truncated']
    if 'complete' in row:
        base['source_scan_complete'] = row['complete']
    result = {**base, 'omitted_items': len(items), key: []}
    if name=='source_map' and mode in ('python_outline','tool_entrypoint'):
        refs=row.get('local_references',[])
        if isinstance(refs,list) and refs:
            chosen=[]
            for ref in refs[:2]:
                if not isinstance(ref,dict) or not isinstance(ref.get('path'),str):break
                chosen.append({k:ref[k] for k in ('path','kind') if k in ref})
                trial={**result,'local_references':chosen,'omitted_references':len(refs)-len(chosen)}
                if len(encode(trial))<=limit//2+len(encode(base))//2:
                    result=trial
                else:break
    if len(encode(result)) > limit:
        minimal = {**base, 'omitted_items': len(items), 'read_exact_history_first': True}
        # Never clip a path/symbol into a misleading partial identifier.
        minimal.pop('path', None)
        minimal.pop('next_tool', None)
        return encode(minimal) if len(encode(minimal)) <= limit else None

    for index, item in enumerate(items):
        if not isinstance(item, dict):
            break
        if mode in ('files', 'ranked_files', 'suggestions'):
            if not isinstance(item.get('path'), str):
                break
            candidate = {'path': item['path']}
            if mode != 'files':
                candidate['rank'] = index + 1
                if 'score' in item:
                    candidate['score'] = item['score']
                if isinstance(item.get('summary'), str):
                    candidate['summary_excerpt'] = item['summary'][:160]
                symbols = item.get('symbols', [])
                if isinstance(symbols, list) and symbols:
                    candidate['symbols'] = [{k:s[k] for k in ('symbol','offset','end_offset') if k in s}
                                            for s in symbols[:2] if isinstance(s, dict)]
        elif mode == 'python_outline':
            candidate = {k:item[k] for k in ('symbol','line','offset','end_offset') if k in item}
            if isinstance(item.get('signature'), str):
                candidate['signature_excerpt'] = item['signature'][:100]
        elif mode == 'tool_entrypoint':
            candidate={k:item[k] for k in ('path','symbol','offset','end_offset','kind','ambiguous') if k in item}
        else:
            candidate = {k:item[k] for k in ('path','line','offset','match_offset','match_kind') if k in item}
            if isinstance(item.get('text'), str):
                candidate['text'] = item['text'][:180]
                if type(item.get('offset')) is int:
                    candidate['next_read_offset'] = item['offset'] + len(candidate['text'])
        trial = {**result, 'omitted_items':len(items)-index-1, key:result[key]+[candidate]}
        if len(encode(trial)) > limit:
            # Keep exact identity and location; shorten only explicitly labeled previews.
            candidate.pop('signature_excerpt', None)
            candidate.pop('symbols', None)
            if 'summary_excerpt' in candidate:
                candidate['summary_excerpt'] = candidate['summary_excerpt'][:80]
            if 'text' in candidate:
                candidate['text'] = candidate['text'][:60]
                if type(candidate.get('offset')) is int:
                    candidate['next_read_offset'] = candidate['offset'] + len(candidate['text'])
            trial = {**result, 'omitted_items':len(items)-index-1, key:result[key]+[candidate]}
        if len(encode(trial)) > limit:
            break  # Preserve a prefix, not a misleading subset of ranked results.
        result = trial
    if mode == 'python_outline' and isinstance(row.get('imports'), list):
        imports = []
        for item in row['imports']:
            if not isinstance(item, dict) or not isinstance(item.get('module'), str):
                continue
            trial = {**result, 'imports': imports+[{'module':item['module']}], 'imports_partial':True}
            if len(encode(trial)) > limit:
                break
            imports = trial['imports']
            result = trial
    if not result[key] and items:
        trial = {**result, 'read_exact_history_first':True}
        if len(encode(trial)) <= limit:
            result = trial
    return encode(result)
