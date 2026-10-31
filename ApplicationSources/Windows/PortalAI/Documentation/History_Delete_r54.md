# Windows r54: selected chat deletion

History allowed multiple selection, but its Delete button used the open chat and
its context menu disabled Delete for groups. Both now delete the explicitly
selected rows. The confirmation shows the count and every selected title in a
scrollable list, with a matching Delete N chats button. Cancel and X remove nothing.

Use Ctrl-click or Shift-select in History, then Delete or right-click > Delete
selected. Read the selected titles before confirming. This removes selected raw
transcripts, their chat-owned attachments and learned memory observations.

The confirmation captures exact IDs and the original store/login, never a later
selection. Empty filtered selection does nothing. Busy/closing state, changed or
revoked login and Stop reject a delayed confirmation. Pending history reads and
searches are cancelled before deletion. An unselected open chat and its attachment
draft stay open; deleting the open chat loads a survivor or creates one empty chat.
Deletion uses the existing per-chat hydration and memory cleanup. A batch is not
an atomic filesystem transaction: errors stop it and report completed histories
and possible incomplete cleanup instead of claiming the whole batch succeeded.

Source: ControlCenter/chat_history_delete.py and native_chat.py. Regression tests:
Maintenance/Tests/test_chat_history_delete.py and test_chat_history_delete_tk.py.
They cover exact selection, cancellation, stale callbacks, filtering, partial
failure, real encrypted dormant chats across sealing/reopening and real Windows
Tk preview scrolling/controls at 720 and 1260 pixels in both themes. Only synthetic
chats are used. No owner conversations were opened or deleted during validation.

Exit and reopen PortalAI normally to load the updated modules. Both SSDs remain
independent Full installations. Windows Full/Academic r54 retain edition policies,
model/runtime pins and the r52/r53 voice/listener repairs. Linux/Mac remain r51.
