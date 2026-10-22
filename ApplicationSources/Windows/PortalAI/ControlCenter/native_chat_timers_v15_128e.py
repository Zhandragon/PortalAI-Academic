# PORTALAI_NICE_TIMERS_v15_136
from __future__ import annotations

"""PortableAI v15.128e live in-chat timing instrumentation."""

import time
import tkinter as tk

VERSION = "15.128e"
INSTALL_MARK = "PORTABLEAI_NATIVE_CHAT_LIVE_TIMERS_v15_128E"


def _fmt(seconds) -> str:
    try: n = max(0, int(float(seconds)))
    except Exception: n = 0
    if n >= 3600:
        return f"{n//3600}:{(n%3600)//60:02d}:{n%60:02d}"
    return f"{n//60:02d}:{n%60:02d}"


def _near_bottom(self):
    try:
        return bool(self._chat_is_near_bottom())
    except Exception:
        return True


def _finalize_segment(timer: dict, now: float | None = None):
    cur = timer.get("current")
    if not cur:
        return
    now = time.monotonic() if now is None else now
    elapsed = max(0.0, now - float(cur.get("started") or now))
    timer.setdefault("segments", []).append((str(cur.get("title") or "Step"), elapsed))
    timer["current"] = None


def _start_stage(self, title: str):
    timer = getattr(self, "_pai128e_timer", None)
    if not timer or not timer.get("active"):
        return
    title = str(title or "Nice")
    cur = timer.get("current")
    if cur and str(cur.get("title")) == title:
        return
    _finalize_segment(timer)
    timer["current"] = {"title": title, "started": time.monotonic()}
    _refresh_labels(self)


def _timeline(timer: dict, now: float) -> str:
    parts = [f"{title} {_fmt(sec)}" for title, sec in (timer.get("segments") or [])[-4:]]
    cur = timer.get("current")
    if cur:
        parts.append(f"{cur.get('title') or 'Step'} {_fmt(now - float(cur.get('started') or now))}")
    return "  →  ".join(parts) if parts else "Nice 00:00"


def _refresh_labels(self):
    timer = getattr(self, "_pai128e_timer", None)
    if not timer:
        return
    now = time.monotonic()
    total = max(0.0, now - float(timer.get("started") or now))
    try:
        timer["steps_label"].configure(text="⏱ " + _timeline(timer, now))
        timer["total_label"].configure(text=f"Response {_fmt(total)}" + ("" if timer.get("active") else " total"))
    except Exception:
        pass
    for block in list(getattr(self, "_trace_blocks", []) or []):
        if block.get("_pai128e_started") is not None and block.get("_pai128e_elapsed") is None:
            try: self._refresh_trace_block_header(block)
            except Exception: pass


def _finish_response(self):
    timer = getattr(self, "_pai128e_timer", None)
    if not timer or not timer.get("active"):
        return
    now = time.monotonic()
    _finalize_segment(timer, now)
    timer["active"] = False
    timer["elapsed"] = max(0.0, now - float(timer.get("started") or now))
    _refresh_labels(self)
    try:
        session = getattr(self, "session", None)
        if isinstance(session, dict):
            ui = int(timer.get("user_index", -1))
            msgs = session.get("messages") or []
            for i in range(len(msgs) - 1, ui, -1):
                if msgs[i].get("role") == "assistant":
                    msgs[i]["response_elapsed_seconds"] = round(float(timer["elapsed"]), 3)
                    self.store.save_session(session)
                    break
    except Exception:
        pass


def _tick(self):
    timer = getattr(self, "_pai128e_timer", None)
    if not timer or not timer.get("active"):
        return
    if not bool(getattr(self, "busy", False)):
        _finish_response(self)
        return
    _refresh_labels(self)
    try:
        self.app.after(250, lambda: _tick(self))
    except Exception:
        pass


def _begin_response(self):
    old = getattr(self, "_pai128e_timer", None)
    if old and old.get("active"):
        _finish_response(self)
    follow = _near_bottom(self)
    frame = tk.Frame(self.chat, bg=self.COL["bg"])
    steps = tk.Label(
        frame, text="⏱ Nice 00:00", bg=self.COL["bg"], fg=self.COL.get("muted", "#999999"),
        anchor="w", font=("Segoe UI Variable Text", 8),
    )
    total = tk.Label(
        frame, text="Response 00:00", bg=self.COL["bg"], fg=self.COL.get("muted", "#999999"),
        anchor="e", font=("Segoe UI Variable Text", 8),
    )
    steps.pack(side="left", padx=(4, 10), pady=(1, 3))
    total.pack(side="right", padx=(10, 4), pady=(1, 3))
    try:
        self.chat.configure(state="normal")
        self.chat.window_create("end", window=frame)
        self.chat.insert("end", "\n")
        self.chat.configure(state="disabled")
    except Exception:
        return
    ui = -1
    try: ui = len((self.session or {}).get("messages") or []) - 1
    except Exception: pass
    now = time.monotonic()
    self._pai128e_timer = {
        "started": now, "active": True, "segments": [],
        "current": {"title": "Nice", "started": now},
        "steps_label": steps, "total_label": total, "frame": frame,
        "user_index": ui,
    }
    if follow:
        try: self.chat.see("end")
        except Exception: pass
    _tick(self)


def install(NativeChat, module_globals: dict) -> None:
    if getattr(NativeChat, "_pai128e_timers_installed", False):
        return

    # Trace-block elapsed time. These wrappers are optional so branch variations do
    # not make the entire PortableAI update fail.
    orig_title = getattr(NativeChat, "_block_title", None)
    if callable(orig_title):
        def block_title(self, block):
            title = orig_title(self, block)
            started = block.get("_pai128e_started") if isinstance(block, dict) else None
            if started is None:
                return title
            elapsed = block.get("_pai128e_elapsed")
            if elapsed is None:
                elapsed = max(0.0, time.monotonic() - float(started))
            return title + " · " + _fmt(elapsed)
        NativeChat._block_title = block_title

    orig_create = getattr(NativeChat, "create_trace_block", None)
    if callable(orig_create):
        def create_trace_block(self, kind, title, *args, **kwargs):
            block = orig_create(self, kind, title, *args, **kwargs)
            state = str(kwargs.get("state", "") or "").lower()
            if isinstance(block, dict) and state in {"live", "running"}:
                block["_pai128e_started"] = time.monotonic()
                block["_pai128e_elapsed"] = None
                try: self._refresh_trace_block_header(block)
                except Exception: pass
            if str(kind).lower() == "tool":
                _start_stage(self, str(title or "Tool"))
            elif str(kind).lower() == "thinking":
                timer = getattr(self, "_pai128e_timer", None)
                if timer and timer.get("active") and not timer.get("current"):
                    _start_stage(self, "Nice")
            return block
        NativeChat.create_trace_block = create_trace_block

    orig_finish = getattr(NativeChat, "finish_trace_block", None)
    if callable(orig_finish):
        def finish_trace_block(self, block, state="done"):
            if isinstance(block, dict) and block.get("_pai128e_started") is not None and block.get("_pai128e_elapsed") is None:
                block["_pai128e_elapsed"] = max(0.0, time.monotonic() - float(block["_pai128e_started"]))
            result = orig_finish(self, block, state)
            if isinstance(block, dict) and str(block.get("kind") or "").lower() == "tool":
                timer = getattr(self, "_pai128e_timer", None)
                if timer and timer.get("active") and bool(getattr(self, "busy", False)):
                    _start_stage(self, "Nice")
            return result
        NativeChat.finish_trace_block = finish_trace_block

    orig_submit = getattr(NativeChat, "submit", None)
    if not callable(orig_submit):
        raise RuntimeError("NativeChat.submit is required for live response timing")
    def submit(self, *args, **kwargs):
        was_busy = bool(getattr(self, "busy", False))
        result = orig_submit(self, *args, **kwargs)
        if not was_busy and bool(getattr(self, "busy", False)):
            _begin_response(self)
        return result
    NativeChat.submit = submit

    orig_regen = getattr(NativeChat, "regenerate_last", None)
    if callable(orig_regen):
        def regenerate_last(self, *args, **kwargs):
            was_busy = bool(getattr(self, "busy", False))
            result = orig_regen(self, *args, **kwargs)
            if not was_busy and bool(getattr(self, "busy", False)):
                _begin_response(self)
            return result
        NativeChat.regenerate_last = regenerate_last

    NativeChat._pai128e_timers_installed = True
