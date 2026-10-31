"""Temporary hands-free views over the existing full and compact chat layouts."""
import tkinter as tk
from voice_visualizer import VoiceVisualizer


def activity_for(panel):
    voice = getattr(panel, '_conversation_io', None)
    active = getattr(panel, 'conversation_active', None)
    return getattr(voice, 'activity', None) if active is not None and active.is_set() else None


def sync_voice_view(panel):
    """Tk-thread only. Keep one visible view of the same voice session."""
    activity = activity_for(panel)
    controller = getattr(getattr(panel, 'app', None), '_portalai_compact_controller', None)
    compact = getattr(controller, '_voice_layout', None)
    in_compact = compact is not None and controller.active
    visualizer = getattr(panel, 'voice_visualizer', None)
    host = getattr(panel, 'voice_host', None)
    if visualizer is not None and host is not None:
        if activity is not None and not in_compact:
            host.grid()
            if visualizer.activity is not activity or not visualizer._visible:
                visualizer.show(activity)
        else:
            visualizer.hide(); host.grid_remove()
    if compact is not None: compact.refresh(activity if in_compact else None)


class CompactVoiceLayout:
    """Swap only the proxy composer; do not rebuild chat, history or controls."""
    def __init__(self, controller):
        self.controller = controller
        self.view = None
        self.saved_composer = None
        self.saved_full_composer = None
        self.active = False
        # Existing bound methods retain all their normal behaviour. Transitions
        # notify this adapter; no layout polling or second microphone is added.
        for name in ('enter', 'exit', 'toggle_chat', '_refresh_colors'):
            original = getattr(controller, name)
            def changed(*args, _original=original, **kwargs):
                result = _original(*args, **kwargs)
                sync_voice_view(controller.native_chat_panel)
                return result
            setattr(controller, name, changed)
        original_geometry = controller._collapsed_geometry
        def geometry():
            width, height = original_geometry()
            if self.active and self.view is not None:
                bar = controller._compact_bar
                top = max(0, bar.winfo_rooty()-controller.app.winfo_rooty())
                height = max(height, top+bar.winfo_reqheight()+24)
            return width, height
        controller._collapsed_geometry = geometry
        original_action = controller._button_action
        def action(*names):
            if any(n.lower().replace('-', ' ') == 'hands free' for n in names):
                return controller.native_chat_panel.toggle_conversation_mode
            return original_action(*names)
        controller._button_action = action

    def refresh(self, activity):
        ctl = self.controller
        row = getattr(ctl, '_composer_row', None)
        if row is None: return
        wanted = activity is not None
        transition = wanted != self.active
        if wanted:
            if not self.active:
                # Save the actual manager/options, including before/after order.
                from portal_frontend_v15136 import _hide_with_snapshot
                self.saved_composer = _hide_with_snapshot(row)
                full = getattr(ctl.native_chat_panel, 'composer_shell', None)
                if full is not None and full.winfo_manager():
                    self.saved_full_composer = _hide_with_snapshot(full)
            if self.view is None:
                self.view = VoiceVisualizer(ctl._compact_bar, ctl.native_chat_panel.COL,
                                            on_end=ctl.native_chat_panel.stop_conversation_mode)
            if self.view.palette != ctl.native_chat_panel.COL:
                self.view.apply_palette(ctl.native_chat_panel.COL)
            if self.view.activity is not activity or not self.view._visible:
                self.view.show(activity)
        else:
            if self.view is not None: self.view.hide()
            if self.saved_composer is not None:
                from portal_frontend_v15136 import _restore_snapshot
                _restore_snapshot(self.saved_composer)
                self.saved_composer = None
            if self.saved_full_composer is not None:
                from portal_frontend_v15136 import _restore_snapshot
                _restore_snapshot(self.saved_full_composer)
                self.saved_full_composer = None
        self.active = wanted
        if transition and ctl.active:
            ctl._compact_bar.update_idletasks()
            ctl._set_size(ctl.expanded)


def install_compact_voice(controller):
    if not hasattr(controller, '_voice_layout'):
        controller._voice_layout = CompactVoiceLayout(controller)
    sync_voice_view(controller.native_chat_panel)
    return controller
