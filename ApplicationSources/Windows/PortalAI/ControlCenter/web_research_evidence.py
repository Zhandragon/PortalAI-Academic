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


def project_images(row, message_id, limit):
    """Retain exact image/source pairs rather than a generic truncated tail."""
    encode=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':'))
    images=row['images']
    view={'kind':'page_image_candidates','url':row['url'],'message_id':message_id,
          'document':row.get('document'),'source':'Read page text and image links (untrusted); image subject not verified.',
          'exact':'chat_history action=read','images':[],'omitted_images':len(images)}
    if len(encode(view))>limit:return None
    # Image metadata must not displace all article/profile text in ordinary
    # research. Keep a bounded head/tail excerpt with explicit truncation.
    text=row.get('text','')
    if isinstance(text,str) and text:
        count=min(1200,limit//3)
        snippet=text if len(text)<=count else text[:count//2]+' ... '+text[-count//2:]
        trial={**view,'text_excerpt':snippet,'text_truncated':len(text)>count}
        if len(encode(trial))<=limit:view=trial
    for image in images:
        if not isinstance(image,dict) or not isinstance(image.get('image_url'),str):continue
        item={k:image[k] for k in ('image_url','image_role','likely_placeholder','exact_match_verified') if k in image}
        if image.get('alt'):item['alt']=str(image['alt'])[:120]
        trial={**view,'images':view['images']+[item],'omitted_images':len(images)-len(view['images'])-1}
        if len(encode(trial))<=limit:view=trial
    # Page identity/links are retained if space remains; exact transcript is
    # still available when a relevant link falls outside this bounded view.
    links=[]
    for item in row.get('links',[])[:100]:
        if not isinstance(item,dict) or not isinstance(item.get('url'),str):continue
        candidate={'url':item['url'],'text':str(item.get('text',''))[:80]}
        trial={**view,'links':links+[candidate]}
        if len(encode(trial))<=limit:links.append(candidate);view=trial
    return encode(view)
