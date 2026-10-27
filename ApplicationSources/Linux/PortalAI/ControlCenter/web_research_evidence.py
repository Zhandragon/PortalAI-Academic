"""Keep data-page cursors and metadata distinctions when chat context shrinks."""
import json


def project_research(row, message_id, limit):
    shapes={'data_preview':'items','resource_discovery':'resources','catalog_results':'results'}
    key=shapes.get(row.get('kind'))
    if key is None or not isinstance(row.get(key),list):return None
    items=row[key]
    metadata={name:row[name] for name in ('kind','source','url','document','format','provider','query','site','pointer','table','tag',
              'offset','resource_kind','total_items','total_resources','total_results','scan_truncated','maximum_preview_offset','more_available') if name in row}
    encode=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':'))
    def view(count):
        result={**metadata,'message_id':message_id,'view_compacted':True,'omitted_items':len(items)-count,
                'exact':'chat_history action=read for complete saved records; omitted items are not analyzed.',key:items[:count]}
        if key in ('items','resources'):
            start=row.get('offset',0);maximum=row.get('maximum_preview_offset',2000 if key=='resources' else 10000)
            if type(start) is not int or type(maximum) is not int:return None
            result['source_next_offset']=row.get('next_offset')
            if count<len(items):
                # A compacted view must not silently jump over unseen records.
                result['next_offset']=start+count if count and start+count<=maximum else None
                result['more_available']=True
            else:result['next_offset']=row.get('next_offset')
            result['read_exact_history_first']=count==0 and bool(items)
        return result
    result=view(0)
    if result is None or len(encode(result))>limit:return None
    for count in range(1,len(items)+1):
        candidate=view(count)
        if len(encode(candidate))>limit:break
        result=candidate
    return encode(result)
