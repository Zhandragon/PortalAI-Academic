"""Structure-aware bounded chunks and transparent retrieval heuristics."""
import re


def chunks(pages):
    for location, source in pages:
        text = source.replace('\x00', '')
        heading = []; table_header = text.split('\n',1)[0] if location.startswith('sheet ') else ''; previous = ''; buffer = ''; start = offset = 0
        def emit(value, position):
            title = ' / '.join(heading)
            context = ('Heading: ' + title + '\n') if title else ''
            if table_header and table_header not in value: context += 'Table header: ' + table_header[:250] + '\n'
            return location + (' · ' + title[:180] if title else ''), position, context + value.strip()
        for line in text.splitlines(keepends=True):
            match = re.match(r'^\s{0,3}(#{1,6})\s+(\S.*)', line)
            table = '|' in line
            if match or (buffer and len(buffer) + len(line) > 1100):
                if buffer.strip():yield emit(buffer, start)
                buffer = ''
            if match:
                heading = heading[:len(match[1]) - 1] + [match[2].strip()[:180]]
                table_header = ''
            if table and re.fullmatch(r'[\s|:\-]+', line) and previous.strip(): table_header = previous.strip()
            if table_header and not table and line.strip():
                if buffer.strip():yield emit(buffer,start);buffer=''
                table_header = ''
            # Long lines are split without discarding a tail; ordinary rows stay intact.
            remaining = line; consumed = 0
            while len(remaining) > 1100:
                if buffer.strip(): yield emit(buffer, start); buffer = ''
                yield emit(remaining[:1100], offset + consumed)
                remaining = remaining[1100:]; consumed += 1100
            if not buffer: start = offset + consumed
            buffer += remaining; previous = line; offset += len(line)
        if buffer.strip(): yield emit(buffer, start)


STOP = {'the', 'a', 'an', 'and', 'or', 'of', 'to', 'is', 'are', 'in', 'on', 'for', 'what', 'how', 'does', 'do', 'can', 'which', 'with'}


def diverse(rows, limit, query):
    wanted = set(re.findall(r'\w+', query.casefold())) - STOP
    result = []; seen = []
    for row in sorted(rows, key=lambda r: r['score'], reverse=True):
        tokens = set(re.findall(r'\w+', row['text'].casefold()))
        if any(len(tokens & old) / max(1, len(tokens | old)) > .82 for old in seen): continue
        seen.append(tokens)
        row['matched_terms'] = sorted(wanted & tokens)[:24]
        row['evidence_hint'] = 'weak match' if not row['matched_terms'] and row.get('semantic_similarity', 0) < .3 else 'candidate passage'
        result.append(row)
        if len(result) >= limit: break
    insufficient = not result or all(r['evidence_hint'] == 'weak match' for r in result)
    return result, {'status': 'insufficient_matches' if insufficient else 'requires_claim_check',
        'notice': 'Heuristic match strength, not calibrated confidence. Verify each claim, table heading, date and exception; read neighboring passages. Say when the indexed evidence cannot answer.'}
