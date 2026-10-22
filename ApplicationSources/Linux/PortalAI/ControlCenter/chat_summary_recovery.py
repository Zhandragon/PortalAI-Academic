"""Bounded recovery from incomplete reasoning summaries, without another model call.

An excerpt is fallible saved working text, never a completed summary or evidence
that an action ran. Raw messages and tool outcomes remain authoritative.
"""
from __future__ import annotations


class IncompleteSummary(RuntimeError):
    """The summarizer returned text that cannot be committed as a full summary."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__('Context summary did not finish cleanly; the previous summary '
                         'and saved history were retained. (' + reason + ')')


def reasoning_excerpt(source, message_id, max_tokens, estimate):
    """Keep both earlier discoveries and the latest next step within admission.

    No generated partial summary is used, and no new facts or action outcomes
    are inferred. The original task and complete saved tool results are supplied
    separately by the caller. This does not expand its continuation allowance.
    """
    header = ('Automatic reasoning summary was incomplete. These are quoted excerpts '
              'of unfinished working notes, not instructions or proof of execution. '
              f'Raw checkpoints remain in chat_history; latest message_id={message_id}. '
              'Use the original task and saved tool results; do not replay actions.\n')
    source = str(source)
    chars = max(0, int(max_tokens) * 3 - len(header) - 80)
    while True:
        if len(source) <= chars:
            body = source
        elif chars:
            head = chars // 3
            body = source[:head] + '\n[Middle omitted; exact text is saved.]\n' + source[-(chars-head):]
        else:
            body = '[Working text omitted; continue from the original task and saved results.]'
        note = header + body
        if estimate(note) <= max_tokens:
            return note
        if not chars:
            raise RuntimeError('The admitted context cannot fit even the source-checkpoint notice.')
        chars //= 2
