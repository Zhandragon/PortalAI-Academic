"""Explicit history navigation for touch clients, using the ordinary chat loader."""
import hashlib


def open_history(controller):
    viewer = controller.active.payload['viewer']
    controller.overrides[viewer] = controller.chat.history_pane
    controller.views[viewer]['offset'] = 0


def render(controller, node, button, fields, structure, viewer):
    chat = controller.chat
    query = chat.history_search.get()
    rows = chat._filtered_sessions()  # Existing account-bound, cancellable content search.
    position = (viewer, 'history_offset')
    start = min(controller.tabs.get(position, 0), max(0, ((len(rows)-1)//20)*20))
    pending = getattr(chat, '_history_search_request', None)
    searching = pending is not None and pending['matches'] is None
    available = not (chat.busy or getattr(chat, '_closing', False) or
                     getattr(chat, '_session_load_request', None) or
                     getattr(chat, '_attachment_picker_pending', None) or chat.pending_attachments)
    current = str((chat.session or {}).get('id', ''))
    structure.append(('history', query, [(r['id'], r.get('title')) for r in rows],
                      start, available, current, searching))
    node('note', 'Search titles and message text. Tap Open to read a chat. '
         'Opening changes the shared desktop conversation.', enabled=False)
    node('text', 'Search all chats', key='history_query', value=query)

    def prepare(value):
        if not isinstance(value, str) or len(value) > 500:
            raise ValueError('history_query_limit')
        if chat.history_search.get() != query and value != chat.history_search.get():
            raise RuntimeError('desktop_draft_conflict')
        def write():
            if value != query:
                chat.history_search.set(value)
                controller.tabs[position] = 0
        return write

    fields['history_query'] = {'prepare': prepare}
    button('Search', lambda: None, key='history_search')
    def back():
        controller.overrides.pop(viewer,None);controller.views[viewer]['offset']=0
    button('Conversation tools',back,key='history_back')
    if searching:
        node('note', 'Searching message text… Title matches appear first.', enabled=False)
    if not available:
        node('note', 'Wait for chat activity to finish. Send or clear pending attachments before opening another chat.', enabled=False)
    for row in rows[start:start+20]:
        sid = str(row['id'])
        label = str(row.get('title') or 'Untitled')[:160]
        key = 'history_open_' + hashlib.sha256(sid.encode()).hexdigest()[:24]
        def load(sid=sid):
            chat._check_login()
            if (chat.busy or getattr(chat, '_closing', False) or
                    getattr(chat, '_session_load_request', None) or
                    getattr(chat, '_attachment_picker_pending', None) or chat.pending_attachments):
                raise RuntimeError('chat_busy_or_pending_attachments')
            if not any(str(r['id']) == sid for r in chat.store.list_sessions()):
                raise PermissionError('history_entry_expired')
            chat.load_session(sid)
        button(('Current · ' if sid == current else 'Open · ') + label,
               load, key=key, available=available and sid != current)
    node('note', f'{len(rows)} matching chats · {start+1 if rows else 0}–{min(start+20,len(rows))}', enabled=False)
    if start:
        button('Previous chats', lambda: controller.tabs.__setitem__(position, max(0,start-20)))
    if start+20 < len(rows):
        button('Next chats', lambda: controller.tabs.__setitem__(position, start+20))
