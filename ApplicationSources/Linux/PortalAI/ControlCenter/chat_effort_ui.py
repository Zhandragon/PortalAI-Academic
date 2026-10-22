"""Compact chat effort controls; model switching is delegated to the lifecycle API."""
from __future__ import annotations

import importlib
from pathlib import Path
import sys
import threading
import time
import tkinter as tk

from elegant_native_ui import ElegantButton

LEVELS = ('fast', 'balanced', 'deep')


def requires_vision(session):
    """Images still in the uncompressed chat context cannot become silent text."""
    session = session or {}
    cursor = max(0, int((session.get('context_state') or {}).get('cursor') or 0))
    for message in (session.get('messages') or [])[cursor:]:
        if message.get('role') != 'user':
            continue
        content = message.get('content')
        if isinstance(content, list) and any(isinstance(row, dict) and row.get('type') == 'image_url' for row in content):
            return True
        for attachment in message.get('attachments') or []:
            if (str(attachment.get('mime') or '').startswith('image/') or
                Path(str(attachment.get('path') or '')).suffix.lower() in
                    ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff')):
                return True
    return False


def model_label(model):
    if isinstance(model, dict):
        model = model.get('id') or model.get('path') or model.get('model') or ''
    value = str(model or '')
    low = value.lower()
    if 'qwen-vl2' in low or 'qwen3vl-2b' in low or 'qwen3-vl-2b' in low:
        return '2B Vision Abliterated' if 'abliterated' in low else '2B Vision'
    if 'qwen-vl4' in low or 'qwen3vl-4b' in low or 'qwen3-vl-4b' in low:
        return '4B Vision Abliterated' if 'abliterated' in low else '4B Vision'
    if '27' in low:
        if 'abliterated' in low or low in {'qwen27-q4', 'qwen27-q5'}:
            return '27B Abliterated'
        if 'standard' in low or 'qwen3.8-27b-q4_k_m.gguf' in low:
            return '27B Standard'
        return '27B'
    if '1.7' in low:
        return '1.7B Abliterated' if 'abliterated' in low else '1.7B'
    if 'qwen4' in low or 'qwen3-4b' in low or 'qwen3.8-4b' in low:
        return '4B Abliterated' if 'abliterated' in low else '4B'
    return Path(value).name if value else 'hardware auto'


def completion_options(result):
    """Allow only inference budget/template settings, never tools or messages."""
    data = result.get('completion_options') or {}
    output = {}
    if data.get('max_tokens') is not None:
        output['max_tokens'] = max(32, min(32768, int(data['max_tokens'])))
    if isinstance(data.get('chat_template_kwargs'), dict):
        thinking = data['chat_template_kwargs'].get('enable_thinking')
        if isinstance(thinking, bool):
            output['chat_template_kwargs'] = {'enable_thinking': thinking}
            reasoning = data['chat_template_kwargs'].get('reasoning_effort')
            if thinking and reasoning in ('low', 'medium', 'xhigh'):
                output['chat_template_kwargs']['reasoning_effort'] = reasoning
    return output


class ChatEffortControls:
    def __init__(self, panel, parent):
        self.panel = panel
        try:
            preferences = self._module('effort_policy').load_preferences(panel.root)
        except Exception:
            preferences = {}
        selected = preferences.get('chat', 'balanced')
        self.profile = str(selected).lower()
        if self.profile not in LEVELS:
            self.profile = 'balanced'
        self.tools_profile = str(preferences.get('tools', 'balanced')).lower()
        if self.tools_profile not in LEVELS:
            self.tools_profile = 'balanced'
        self.active_tools_profile = self.tools_profile
        self.session_unlocked = False
        self.active_options = {}
        self.active_plan = None
        self.capability_data = None
        self._probe_serial = 0
        self._details = None
        self.on_choice_saved = None
        self._choice_signature = None
        colors = panel.COL
        self.widget = tk.Frame(parent, bg=colors['panel'])
        tk.Label(self.widget, text='Chat effort', bg=colors['panel'], fg=colors['muted'],
                 font=('Segoe UI Variable Text', 8)).pack(side='left', padx=(5, 2))
        from gold_controls import GoldScale
        self.scale = GoldScale(self.widget,from_=0,to=2,resolution=1,length=86,
                               palette=colors,command=self._changed)
        self.scale.set(LEVELS.index(self.profile))
        self.scale.pack(side='left', padx=2)
        self.label = tk.Label(self.widget, text=self.profile.title(), bg=colors['panel'],
                              fg=colors['cyan'], font=('Segoe UI Variable Text', 8))
        self.label.pack(side='left', padx=2)
        self.uncensored = tk.BooleanVar(self.widget, value=False)
        self.variant_check = tk.Checkbutton(self.widget, text='Uncensored', variable=self.uncensored,
            command=self._variant_changed, bg=colors['panel'], fg=colors['text'],
            activebackground=colors['panel'], activeforeground=colors['text'],
            selectcolor=colors['panel2'], font=('Segoe UI Variable Text', 8), bd=0, highlightthickness=0)
        self.variant_check.pack(side='left', padx=(4, 2))
        self.variant_check.configure(state='disabled')
        from academic_policy import bind_help
        bind_help(self.variant_check)
        self.details_button = ElegantButton(self.widget, text='\u2026', command=self.open_details,
            bg=colors['panel2'], fg=colors['text'], relief='flat', bd=0, padx=6, pady=3)
        self.details_button.pack(side='left', padx=2)
        self.sync_saved_choice(refresh=False)
        panel.app.after(250, self.refresh_capabilities)

    def _module(self, name):
        agent = str(Path(self.panel.root) / 'Agent')
        if agent not in sys.path:
            sys.path.insert(0, agent)
        return importlib.import_module(name)

    def sync_saved_choice(self, *, refresh=True, policy=None, preferences=None):
        if self.panel.busy: return  # Keep the current request's admitted options intact.
        if policy is None: policy = self._module('runtime_policy').load_effective_policy(self.panel.root)
        if preferences is None: preferences = self._module('effort_policy').load_preferences(self.panel.root)
        variant = self._module('chat_selection').selected_variant(policy)
        signature = (policy.get('selection'), variant, policy.get('backend'),
                     policy.get('context_tokens'), preferences['chat'])
        if signature == self._choice_signature: return
        self._choice_signature = signature
        self.profile = preferences['chat']
        self.scale.set(LEVELS.index(self.profile)); self.uncensored.set(variant == 'uncensored')
        self.active_options = {}; self.active_plan = None; self.capability_data = None
        self._probe_serial += 1  # Discard an old variant/model probe immediately.
        self._render()
        if refresh: self.refresh_capabilities()

    def _save_model_choice(self, *, level=None, uncensored=None):
        from account_permissions import require_user
        require_user(self.panel.root, getattr(self.panel.app, '_portalai_account_session', None))
        policy = self._module('runtime_policy').load_effective_policy(self.panel.root)
        changes = self._module('chat_selection').choice_changes(
            self.panel.root, policy, level=level, uncensored=uncensored)
        self._module('model_preferences').save(self.panel.root, changes)
        self.sync_saved_choice()
        if self.on_choice_saved: self.on_choice_saved()

    def _variant_changed(self):
        self.uncensored.set(False)
        return

    def _changed(self, value):
        chosen = LEVELS[max(0, min(2, int(float(value))))]
        if chosen == self.profile:
            return
        if self.panel.busy:
            self.scale.set(LEVELS.index(self.profile))
            return
        plan = ((self.capability_data or {}).get('profiles') or {}).get(chosen) or {}
        if plan and not plan.get('can_apply', False):
            self.scale.set(LEVELS.index(self.profile))
            self.panel._notice('Chat effort', str(plan.get('reason') or plan.get('warning') or
                'This profile is not available on the current hardware.') +
                ('\n\nOpen the effort details (\u2026) to unlock slower profiles for this session.'
                 if plan.get('locked') else ''), kind='warning')
            return
        try:
            self._save_model_choice(level=chosen)
        except Exception as exc:
            self.scale.set(LEVELS.index(self.profile))
            self.panel._notice('Chat effort', 'Could not save the chat preference: ' + str(exc), kind='error')
            return
        self.profile = chosen
        self.active_options = {}
        self._render()
        self.refresh_capabilities()

    def refresh_capabilities(self):
        if self.panel.busy:
            return
        self._probe_serial += 1
        serial = self._probe_serial
        unlocked = self.session_unlocked
        def probe():
            try:
                result = self._module('effort_policy').capabilities(
                    self.panel.root, session_unlocked=unlocked, size_choices=True)
            except Exception as exc:
                result = {'error': str(exc), 'profiles': {}}
            self.panel.ev.put(('effort_capabilities', {'serial': serial, 'result': result}))
        threading.Thread(target=probe, name='PortalAIChatEffortProbe', daemon=True).start()

    def _change_tools(self, chosen):
        if self.panel.busy or chosen not in LEVELS:
            return False
        plan = ((self.capability_data or {}).get('profiles') or {}).get(chosen) or {}
        if plan.get('locked'):
            self.panel._notice('Tool effort', str(plan.get('warning') or 'This profile may be slow on this hardware.')
                + '\n\nUnlock slower profiles for this session first.', kind='warning')
            return False
        try:
            self._module('effort_policy').save_preferences(self.panel.root, tools=chosen)
        except Exception as exc:
            self.panel._notice('Tool effort', 'Could not save the tool preference: ' + str(exc), kind='error')
            return False
        self.tools_profile = chosen
        self._render()
        return True

    def receive_capabilities(self, value):
        if value.get('serial') != self._probe_serial:
            return
        self.capability_data = value.get('result') or {}
        self._render()

    def _render(self):
        plan = ((self.capability_data or {}).get('profiles') or {}).get(self.profile) or {}
        applied = self.active_plan if self.active_plan and self.active_plan.get('profile') == self.profile else {}
        chosen = model_label(applied.get('model') or plan.get('model') or plan.get('selection'))
        # The checkbox already shows variant; keep the compact row readable.
        chosen = chosen.replace(' Abliterated', '').replace(' Standard', '')
        suffix = (' \u00b7 locked' if plan.get('locked') else
                  ' \u00b7 unavailable' if plan and not plan.get('available') else
                  ' \u00b7 ' + chosen if plan else '')
        self.label.configure(text=self.profile.title() + suffix,
                             fg=self.panel.COL['gold'] if plan.get('locked') else self.panel.COL['cyan'])
        if self._details is not None:
            try:
                if self._details.winfo_exists():
                    self._details.configure(text=self.details_text())
            except tk.TclError:
                self._details = None

    def details_text(self):
        lines = [
            'Fast selects 1.7B, Balanced selects 4B, and Deep selects 27B. '
            'Uncensored independently chooses the matching abliterated variant; unchecked uses Standard. '
            'The model and variant synchronize with Settings. Automatic in Settings retains hardware fallback.',
            'Model size controls much of the speed difference: 1.7B is lighter than 4B, and 4B is lighter than 27B. '
            'The slider also sets reasoning, generated-token allowance and model wait budgets. Tool calls use the separate Chat Preferences budget. '
            'Generated tokens include both thinking and the visible answer. A longer budget does not guarantee a better answer.',
            'Changes apply to the next chat request. Media and science effort settings are separate.',
            'Automatic image vision in Settings temporarily uses 2B with Fast or 4B with Balanced '
            '(2B fallback if needed), matching Uncensored. The saved text choice is unchanged. '
            'Images remaining in the active conversation context continue to require vision.',
            'The hardware preview is checked again after reclaiming owned model memory, before loading another model.',
            'Media/science effort: ' + self.tools_profile.title() + '. Omitted defaults currently change for SD1.5 images, short video generation, SFX generation and transcription. '
            'Other media tools retain their hardware-scaled defaults. '
            'Explicit sizes, duration, steps and scientific precision are retained. Science effort guides planning and verification.',
        ]
        data = self.capability_data or {}
        if data.get('error'):
            lines.append('Hardware check: ' + data['error'])
        for name in LEVELS:
            plan = (data.get('profiles') or {}).get(name)
            if not plan:
                continue
            state = ('locked' if plan.get('locked') else 'available' if plan.get('can_apply') else 'unavailable')
            model = model_label(plan.get('model') or plan.get('selection'))
            thinking = plan.get('thinking')
            reasoning = 'model default' if thinking is None else 'on' if thinking else 'off'
            if thinking and (plan.get('chat_template_kwargs') or {}).get('reasoning_effort'):
                reasoning += ' (' + plan['chat_template_kwargs']['reasoning_effort'] + ')'
            lines.append(f"{name.title()}: {model}; reasoning {reasoning}; "
                         f"up to {plan.get('max_tokens', '?')} output tokens; {state}. "
                         + str(plan.get('reason') or plan.get('warning') or ''))
        if self.active_plan:
            lines.append('Last applied: ' + str(self.active_plan.get('profile', self.profile)).title()
                         + ' \u00b7 ' + model_label(self.active_plan.get('model')))
        return '\n\n'.join(lines)

    def open_details(self):
        # Both entry points use the same staged controls and Save/Cancel contract.
        self.panel.open_settings()
        self.panel._preferences_tabs.select('effort')

    def preferences_controls(self, parent, skin):
        draft = {'chat': tk.StringVar(parent, value=self.profile),
                 'tools': tk.StringVar(parent, value=self.tools_profile),
                 'unlock': tk.BooleanVar(parent, value=self.session_unlocked)}
        for key, title in (('chat', 'Chat effort'), ('tools', 'Media / science effort')):
            skin.row(parent, title, lambda row, key=key: skin.combo(row, draft[key], list(LEVELS)))
        skin.check(parent, 'Unlock slower profiles for this session', draft['unlock'])
        skin.label(parent, 'Save applies chat size and synchronizes Settings; the Uncensored checkbox selects the variant. Changes take effect on the next request. Unlock never bypasses RAM, VRAM, backend or storage admission. Stop still cancels continuation.', muted=True).pack(fill='x', pady=5)
        self._details = skin.label(parent, self.details_text(), muted=True)
        self._details.pack(fill='x', pady=5)
        skin.button(parent, 'Refresh hardware check', self.refresh_capabilities).pack(anchor='w', pady=4)
        return draft

    def save_preferences_draft(self, draft):
        chat, tools, unlock = draft['chat'].get(), draft['tools'].get(), bool(draft['unlock'].get())
        if (chat, tools, unlock) == (self.profile, self.tools_profile, self.session_unlocked): return
        if self.panel.busy: raise ValueError('Wait for the current response before changing effort.')
        if chat not in LEVELS or tools not in LEVELS: raise ValueError('Unknown effort choice')
        for name, current in ((chat, self.profile), (tools, self.tools_profile)):
            if name == current: continue
            plan = ((self.capability_data or {}).get('profiles') or {}).get(name) or {}
            if plan.get('locked') and not unlock:
                raise ValueError('Unlock slower profiles for this session before selecting '+name+'.')
            if name == chat and plan and not plan.get('can_apply') and not plan.get('locked'):
                raise ValueError(plan.get('reason') or 'This effort is unavailable on this hardware.')
        if chat != self.profile: self._save_model_choice(level=chat)
        self._module('effort_policy').save_preferences(self.panel.root, tools=tools)
        self.profile, self.tools_profile, self.session_unlocked = chat, tools, unlock
        self.active_options = {}
        self.scale.set(LEVELS.index(chat)); self._render(); self.refresh_capabilities()

    def prepare_request(self, cancel_event):
        """Worker-only entry: snapshot the request before any inference or tool."""
        profile = self.profile
        unlocked = self.session_unlocked
        tools = self.tools_profile
        self.active_options = {}
        if cancel_event.is_set():
            return False
        vision = requires_vision(getattr(self.panel, 'session', None))
        result = self._module('chat_model_switch').prepare_chat(
            self.panel.root, profile, unlock_slow=unlocked, cancel_event=cancel_event,
            requested_at=time.time(), require_vision=vision,
            on_status=lambda message: self.panel.ev.put(('connection_status', str(message))))
        if cancel_event.is_set():
            return False
        self.active_plan = result
        self.active_options = completion_options(result)
        self.active_tools_profile = tools
        self.panel.tool_runtime.set_request_effort(tools, unlocked)
        self.panel._model_context_limit = None
        self.panel._model_context_checked = 0.0
        self.panel.ev.put(('effort_applied', result))
        return True

    def set_busy(self, busy):
        self.scale.configure(state='disabled' if busy else 'normal')
        self.variant_check.configure(state='disabled' if busy else 'normal')
        if not busy:
            self.sync_saved_choice()
            self._render()

    def apply_palette(self):
        colors = self.panel.COL
        self.scale.apply_palette(colors)
        self.variant_check.configure(bg=colors['panel'], fg=colors['text'],
            activebackground=colors['panel'], activeforeground=colors['text'], selectcolor=colors['panel2'])

