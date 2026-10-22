"""Bounded process errors that retain the cause of a native crash."""


def excerpt(text,limit=4500):
    if limit<128:raise ValueError('Diagnostic limit is too small')
    text=str(text)
    fatal=text.find('Fatal Python error:')
    if fatal>=0:
        # Faulthandler's module inventory can dwarf the useful native stack.
        end=text.find('\nExtension modules:',fatal)
        if end>=0:text=text[:end]
    if len(text)<=limit:return text
    separator='\n... diagnostic middle omitted ...\n'
    if fatal>=0:
        start=max(0,text.rfind('\n',0,fatal-1)+1)
        text=text[start:]
    if len(text)<=limit:return text
    first=(limit-len(separator))*2//3
    last=limit-len(separator)-first
    return text[:first]+separator+text[-last:]


def file_excerpt(path,limit=4500):
    # Preserve bounded reading even if an unsuccessful startup floods its log.
    with path.open('rb') as source:
        source.seek(max(0,path.stat().st_size-128*1024))
        return excerpt(source.read().decode('utf-8',errors='replace'),limit)
