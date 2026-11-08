# Follow-up messages in Chat

While Nice is working, enter a message and use **Queue** or Enter. Pending messages run in order after the current reply. **Send now** interrupts the current request, waits for worker cleanup, then starts the first queued follow-up. Completed tool effects are not undone or automatically repeated.

**Edit next** returns the first pending message to an empty composer; send the edit to put it back first. **Remove next** discards that pending message. Stop or a failed request pauses the queue; resume with Send now. New unsent composer drafts are preserved while queued messages are sent.

The queue is in memory for the current chat and profile, with at most 32 pending messages. Changing chats/accounts or closing PortalAI clears unsent queued messages. Each enters saved history only when sent. Wait for attachment copying to finish before queuing. Remote API/HA requests retain their existing busy admission instead of silently entering the desktop queue.

The Windows long-path wrapper also avoids Python 3.13 path-protocol recursion. Existing dependencies, model selections, Academic restrictions and stored account data are unchanged.
