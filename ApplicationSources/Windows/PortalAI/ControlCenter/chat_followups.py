"""Session-scoped, in-memory follow-ups; only the GUI thread changes this queue."""
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class Followup:
    text: str
    attachments: tuple
    recover_coding: bool = False


class FollowupQueue:
    def __init__(self):
        self.scope = None
        self.items = deque()
        self.paused = False
        self.interrupt_requested = False
        self.editing = False

    def bind(self, scope):
        if scope != self.scope:
            self.clear()
            self.scope = scope

    def clear(self):
        self.items.clear()
        self.paused = False
        self.interrupt_requested = False
        self.editing = False

    def add(self, text, attachments, *, recover_coding=False):
        if len(self.items) >= 32:
            raise ValueError('The follow-up queue is full. Edit or remove a queued message first.')
        entry = Followup(text, tuple(dict(a) for a in attachments), bool(recover_coding))
        if self.editing:
            self.items.appendleft(entry)
            self.editing = False
            self.paused = False
        else:
            self.items.append(entry)
        return entry

    def take_for_edit(self):
        entry = self.peek()
        if entry is not None:
            self.commit(entry)
            self.pause()
            self.editing = True
        return entry

    def peek(self):
        return self.items[0] if self.items else None

    def commit(self, entry):
        if self.peek() is not entry:
            raise RuntimeError('The queued follow-up changed before it could be sent.')
        self.items.popleft()

    def pause(self):
        self.paused = True
        self.interrupt_requested = False

    def send_now(self):
        if self.items:
            self.paused = False
            self.interrupt_requested = True

    def completed(self, *, cancelled=False, failed=False):
        if (cancelled or failed) and not self.interrupt_requested:
            self.paused = True
        self.interrupt_requested = False
        return bool(self.items) and not self.paused
