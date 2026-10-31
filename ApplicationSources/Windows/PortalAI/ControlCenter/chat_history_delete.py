"""Delete an explicitly selected, previewed history batch under its original login."""


def delete_selected(chat):
    if chat.busy or getattr(chat, '_closing', False):
        return
    chat._check_login()
    # A filtered empty list must not fall back to an invisible open chat.
    if not chat.session_list.curselection():
        return
    sids = tuple(dict.fromkeys(chat._selected_history_ids()))
    if not sids:
        return
    store, memory = chat.store, chat.memory
    rows = {str(row['id']): row for row in store.list_sessions()}
    if any(sid not in rows for sid in sids):
        chat._notice('Delete chats', 'History changed. Select the chats again.', kind='warn')
        return
    titles = tuple(' '.join(str(rows[sid].get('title') or 'Untitled').split()) for sid in sids)
    token = chat._history_delete_request = object()

    def perform():
        if (getattr(chat, '_history_delete_request', None) is not token
                or chat.busy or getattr(chat, '_closing', False)
                or chat.store is not store or chat.memory is not memory):
            return
        chat._history_delete_request = None  # One confirmation cannot run twice.
        chat._check_login()
        # Prevent an already queued read/search from publishing deleted history.
        timer = getattr(chat, '_session_load_after', None)
        if timer is not None:
            chat.app.after_cancel(timer)
            chat._session_load_after = None
        for name in ('_session_load_request', '_history_search_request'):
            pending = getattr(chat, name, None)
            if pending is not None:
                pending['cancel'].set()
                setattr(chat, name, None)
        memory.cancel_active()
        deleted = []
        error = None
        try:
            for sid in sids:
                chat._check_login()
                store.delete_session(sid)
                deleted.append(sid)
                try:
                    memory.forget_chat(sid)
                except Exception:
                    # A transcript may already be gone; do not replay its delete.
                    memory.prune_orphans_from_disk()
        except Exception as exc:
            error = exc
        # Reconcile even a partially completed batch, but never cross login epochs.
        chat._check_login()
        if chat.session and str(chat.session.get('id')) in deleted:
            chat.release_audio_capture()
            chat.session = None
            chat.pending_attachments = []
            chat.render_history()
            remaining = store.list_sessions()
            next_session = remaining[0] if remaining else store.new_session()
            chat.load_session(next_session['id'], synchronous=True)
        elif chat.session is None and deleted:
            remaining = store.list_sessions()
            next_session = remaining[0] if remaining else store.new_session()
            chat.load_session(next_session['id'], synchronous=True)
        chat.refresh_sessions_labels_only()
        chat._update_memory_chat_button()
        if error is not None:
            chat._notice('Delete chats',
                         f'Removed {len(deleted)} of {len(sids)} chat histories before deletion stopped. '
                         'Some attachment or memory cleanup may be incomplete. Review history before trying again.\n\n'
                         + str(error), kind='error')

    count = len(sids)
    chat._confirm(
        'Delete chat' if count == 1 else f'Delete {count} chats',
        f'Delete {count} selected chat' + ('?' if count == 1 else 's?')
        + '\n\nThis removes their raw history, chat-owned attachments, and learned memory observations.',
        perform,
        yes_text='Delete' if count == 1 else f'Delete {count} chats',
        danger=True,
        items=tuple(f'{number}. {title}' for number, title in enumerate(titles, 1)),
    )
