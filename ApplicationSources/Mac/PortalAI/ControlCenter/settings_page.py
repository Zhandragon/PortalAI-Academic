"""Visible themed settings, independent of the GUI's lifecycle buttons."""
from pathlib import Path
import math
import shutil
import queue
import threading
import tkinter as tk
from bundle_inventory import inventory, MODEL_LABELS
from runtime_policy import load_policy, load_effective_policy, atomic_json, build_plan, storage_budget
from model_preferences import CHAT_KEYS, MEDIA_CHOICES, save as save_personal
from account_permissions import require_admin, can_admin, require_user, can_user
from settings_style import SettingsSkin, SettingsTabs
from media_choices import CHOICES as MEDIA_DESCRIPTIONS, TITLES as MEDIA_TITLES
from chat_selection import selected_variant


def policy_values(policy):
    return {'selection': policy.get('selection', 'auto'), 'backend': policy.get('backend', 'auto'),
            'context_tokens': str(policy.get('context_tokens', 8192)),
            'variant_preference': selected_variant(policy),
            'vision_routing': policy.get('vision_routing', 'off'),
            **{key: policy.get('media', {}).get(key, 'auto') for key in MEDIA_CHOICES}}


def model_inventory_note(models):
    return '\n'.join(f"{'Installed' if model['installed'] else 'Not installed'}: {model['label']}"
                     + (f" ({model['bytes']/1024**3:.2f} GiB)" if model['installed'] else '') for model in models)


def save_settings(root, values, *, session=None, scope='all'):
    require_user(root, session)
    if scope not in ('all','chat','media'):raise ValueError('Unknown settings section')
    policy = load_effective_policy(root)
    changes = {}
    if scope in ('all','chat'):
        available = {m['id'] for m in inventory(root)['models'] if m['installed']}
        if values['selection'] != 'auto' and values['selection'] not in available:
            raise ValueError('The selected model or vision projector is not installed.')
        if values['backend'] not in ('auto', 'cuda', 'vulkan', 'cpu'):raise ValueError('Unknown backend')
        context = int(values['context_tokens'])
        if context not in (2048, 4096, 8192, 16384, 32768):raise ValueError('Unsupported context size')
        changes.update(selection=values['selection'], backend=values['backend'], context_tokens=context,
                       variant_preference=values.get('variant_preference', policy.get('variant_preference', 'standard')),
                       vision_routing=values.get('vision_routing', policy.get('vision_routing', 'off')))
    if scope in ('all','media'):
        media={key:values.get(key,policy.get('media',{}).get(key,'auto')) for key in MEDIA_CHOICES}
        if any(media[k] not in choices for k,choices in MEDIA_CHOICES.items()):raise ValueError('Unknown media setting')
        changes['media'] = media
    if scope == 'all' and any(k in values for k in ('minimum_free_gib','output_reserve_gib','minimum_free_percent')):
        raise ValueError('Save shared storage separately in Storage reserves.')
    save_personal(root, changes)


def media_fit(root, values):
    # Read-only planning, using one hardware snapshot. No handoff, model load or
    # ROCm compute test is requested by this settings preview.
    from runtime_policy import detect_hardware
    from media_policy import image_plan, speech_plan
    from tts_policy import tts_plan
    hardware=detect_hardware();policy=load_effective_policy(root)
    policy.setdefault('media',{}).update({key:values.get(key,'auto') for key in MEDIA_CHOICES})
    results=[]
    for name,planner,fields in (('Images',image_plan,('profile','engine','backend')),
                               ('Transcription',speech_plan,('model','device')),
                               ('Speech',tts_plan,('engine','device'))):
        try:
            plan=planner(root,hardware=hardware,policy=policy)
            results.append(name+': '+' / '.join(str(plan[k]) for k in fields if k in plan))
        except Exception as exc:results.append(name+': '+str(exc))
    from media_defaults import reference_video_scaled
    from native_video import video_plan
    try:
        plan=video_plan(root, engine=values.get('text_video_engine','auto'), hardware=hardware)
        results.append('Text video: Wan 1.3B / '+plan['engine'])
    except Exception as exc:results.append('Text video: '+str(exc))
    for name, route, key in (('Image video',reference_video_scaled,'reference_video_profile'),):
        try:
            scaled=route(values.get(key,'auto'),root=root,hardware=hardware,policy=policy)
            results.append(name+': '+('bounded GPU route' if scaled else 'Windows CUDA service')+'; real GPU probe and job admission still required')
        except Exception as exc:results.append(name+': '+str(exc))
    music = values.get('music_engine', 'auto')
    if music == 'musicgen-cpu':
        try:
            from music_cpu import plan as cpu_music_plan
            cpu_music_plan(root, hardware)
            results.append('Music: MusicGen CPU; instrumental 1–30s, 10 GiB free RAM, noncommercial weights')
        except Exception as exc:results.append('Music: '+str(exc))
    else:
        results.append('Music: '+('compatible ACE-Step GPU, then MusicGen CPU for instrumental 1–30s requests' if music == 'auto' else music)
                       +'; actual GPU probe and memory admission run after chat unload')
    return ' · '.join(results)+'. Estimate at current free memory; job admission runs again after handoff.'


class SettingsPage(tk.Frame):
    def __init__(self, parent, root, colors, missions=None, on_save=None, *, session=None):
        self.root_dir = Path(root); self.on_save = on_save; self.account_session = session
        self.on_change = None; self._syncing = False; self._dirty = set(); self._busy = False
        super().__init__(parent, bg=colors.get('bg', '#EFE8DC'), padx=0, pady=0)
        self.skin = skin = SettingsSkin(self, colors,section_subtitles=True,row_connectors=True,compact=True,section_padx=0)
        skin.remember(self, bg='panel')
        from ornate_ui import ConnectedBorder, install_separator
        skin.borders.append(ConnectedBorder(self,skin.colors,radius=16))
        content=skin.frame(self);content.pack(fill='both',expand=True,padx=12,pady=10)
        skin.label(content, 'Saved model policy and hardware', heading=True).pack(fill='x', padx=3,pady=(0,2))
        self.title_separator=install_separator(content,skin.colors,height=7)
        self.tabs = SettingsTabs(content, skin)
        chat_page = self.tabs.add('chat', 'Chat model and memory')
        media_page = self.tabs.add('media', 'Media defaults')
        from instance_settings import add_tab
        add_tab(self)
        model_section = skin.section(chat_page, 'Chat model and memory')
        def label(parent, text, *, muted=False):
            widget = skin.label(parent, text, muted=muted)
            widget.pack(fill='x', pady=(3, 7))
            return widget
        label(model_section, 'This is an academic version of PortalAI for controlled usage intended as a teaching tool. The abliterated/uncensored version is not available to students.', muted=True)
        d = inventory(root); policy = load_effective_policy(root); self.model_ids = {'Automatic · fit available memory': 'auto'}
        self.model_ids.update({m['label']: m['id'] for m in d['models'] if m['installed'] and not m.get('vision_only')})
        self._installed_choices = [(m['label'], m['id']) for m in d['models'] if m['installed'] and not m.get('vision_only')]
        self._add_missing_selection(policy.get('selection', 'auto'))
        selected = next((k for k,v in self.model_ids.items() if v==policy.get('selection','auto')), 'Automatic · fit available memory')
        self.variables = {}
        self.selectors = {}
        self.media_labels = {}
        self.media_help = {}
        media_section = skin.section(media_page, 'Media defaults')
        from ui_extensions import ResponsiveGrid
        self.media_grid = ResponsiveGrid(media_section, bg=skin.colors['panel'], min_cell_width=390,
                                         max_columns=2, hgap=18, vgap=4)
        skin.remember(self.media_grid, bg='panel'); self.media_grid.pack(fill='x')
        self.media_detail_key = 'media_variant'
        self.media_detail_title = tk.StringVar(self, value='')
        self.media_detail_text = tk.StringVar(self, value='')
        for section, key, title, current, options in (
            (model_section, 'selection', 'Chat model', selected, list(self.model_ids)),
            (model_section, 'variant_preference', 'Chat variant', selected_variant(policy), ['standard','uncensored']),
            (model_section, 'backend', 'Backend', policy.get('backend','auto'), ['auto','cuda','vulkan','cpu']),
            (model_section, 'context_tokens', 'Context limit', str(policy.get('context_tokens',8192)), ['2048','4096','8192','16384','32768']),
            (model_section, 'vision_routing', 'Automatic image vision', policy.get('vision_routing','off'), ['automatic','off']),
        ):
            var = tk.StringVar(self, value=current); self.variables[key] = var
            self.selectors[key] = skin.row(section, title, lambda row, var=var, options=options: skin.combo(row, var, options))
        for key in ('selection', 'variant_preference'):
            self.selectors[key].bind('<<ComboboxSelected>>', lambda event, key=key: self._chat_choice_selected(key), add='+')
        label(model_section, 'The Qwen 3 VL 2B and 4B pairs appear in Models, Packages and the inventory below. They are image companions, so the text-model menu excludes them. Maintenance: Small Vision (2B / 4B) checks files and effort routing; Vision Asset Checksums verifies the pinned files without loading a model. Automatic image vision uses 2B for Fast and 4B for Balanced, falling back to 2B when needed. Academic always uses standard vision companions and keeps your text choice. Images still in conversation context require vision. Save to apply; memory and Stop checks remain.', muted=True)
        for key in MEDIA_DESCRIPTIONS:
            self._media_row(self.media_grid, key, policy.get('media',{}).get(key,'auto'))
        skin.label(media_section, 'Select a dropdown to read its requirements below.', muted=True).pack(fill='x', pady=(5, 2))
        skin.label(media_section, textvariable=self.media_detail_title).pack(fill='x')
        self.media_detail = skin.label(media_section, textvariable=self.media_detail_text, muted=True)
        self.media_detail.pack(fill='x', pady=(2, 6))
        self._show_media_help('media_variant')
        self.statuses={key:tk.StringVar(self,value='') for key in ('chat','media')}
        self.status=self.statuses['chat'];self.results=queue.Queue();self.probing=set()
        self._probe_serial = {'chat': 0, 'media': 0}
        self.saved_values = policy_values(policy)
        allowed=can_user(root,session)
        model_note = model_inventory_note(d['models'])
        media_note=('Applies to the next job. Memory requirements mean FREE memory after chat unload. '
                    'Nice follows saved choices; ask explicitly for a one-off model change. Physical Radeon/Intel/Linux GPU validation is pending.')
        self.section_buttons={}
        for key,section,note in (('chat',model_section,model_note),('media',media_section,media_note)):
            footer=skin.frame(section);footer.pack(fill='x',pady=(4,0))
            summary=skin.label(footer,note,muted=True)
            if key == 'chat':self.inventory_label = summary
            actions=skin.frame(footer)
            from ui_extensions import ResponsiveGrid
            grid=ResponsiveGrid(actions,bg=skin.colors['panel'],min_cell_width=160,max_columns=2,hgap=8,vgap=4)
            skin.remember(grid,bg='panel');grid.pack(fill='x')
            check=skin.button(grid,'Check hardware fit',lambda key=key:self.probe(key));grid.add(check)
            save=skin.button(grid,'Save settings',lambda key=key:self.save(key),state='normal' if allowed else 'disabled');grid.add(save)
            self.section_buttons[key]=(check,save)
            def layout(event,summary=summary,actions=actions,footer=footer):
                stacked=event.width<720
                footer.columnconfigure(0,weight=1);footer.columnconfigure(1,weight=0 if stacked else 1)
                summary.grid(row=0,column=0,columnspan=2 if stacked else 1,sticky='nsew',padx=(0,0 if stacked else 15))
                actions.grid(row=1 if stacked else 0,column=0 if stacked else 1,columnspan=2 if stacked else 1,sticky='sew',pady=(5,0))
            footer.bind('<Configure>',layout)
            status_label=skin.label(section,textvariable=self.statuses[key],muted=True)
            status_label.pack(fill='x',pady=(2,0))
        self.probe_button,self.save_button=self.section_buttons['chat']
        self.allowed = allowed
        for key, var in self.variables.items():
            var.trace_add('write', lambda *_, key=key: self._changed(key))
        for page in (chat_page, media_page):
            label(page,'Chat and media settings save independently with your account on the SSD. Switching subtabs keeps unsaved changes. Storage reserves remain shared.',muted=True)
            if not allowed:label(page,'Sign in to save personal settings.',muted=True)
        from academic_policy import bind_help
        for key in ('variant_preference', 'media_variant'):
            self.variables[key].set('standard')
            self.selectors[key].configure(state='disabled')
            bind_help(self.selectors[key])
        self.poll_id=self.after(250,self.poll)

    def _media_row(self, section, key, current):
        descriptions = MEDIA_DESCRIPTIONS[key]
        var = self.variables[key] = tk.StringVar(self, value=current)
        display = self.media_labels[key] = tk.StringVar(self, value=descriptions[current][0])
        reverse = {row[0]:value for value,row in descriptions.items()}
        row = self.skin.frame(section); section.add(row); row.columnconfigure(0,weight=1)
        self.skin.label(row, MEDIA_TITLES[key]).grid(row=0,column=0,sticky='ew',pady=(0,2))
        combo = self.selectors[key] = self.skin.combo(row, display, list(reverse))
        combo.grid(row=1,column=0,sticky='ew')
        self.media_help[key] = descriptions
        def selected(*_):
            value = reverse.get(display.get())
            if value is not None and value != var.get():var.set(value)
        def synced(*_):
            row = descriptions.get(var.get())
            if row is None:return
            if display.get() != row[0]:display.set(row[0])
            if self.media_detail_key == key:self._show_media_help(key)
        display.trace_add('write', selected)
        var.trace_add('write', synced)
        combo.bind('<FocusIn>', lambda _e:self._show_media_help(key), add='+')
        combo.bind('<<ComboboxSelected>>', lambda _e:self._show_media_help(key), add='+')

    def _show_media_help(self, key):
        self.media_detail_key = key
        label, note = MEDIA_DESCRIPTIONS[key][self.variables[key].get()]
        self.media_detail_title.set(MEDIA_TITLES[key]+': '+label)
        self.media_detail_text.set(note)

    def apply_palette(self, colors):
        self.skin.apply_palette(colors)
        self.title_separator._portableai_palette.update(colors)
        self.title_separator.configure(bg=colors['panel'])
        self.title_separator._portableai_redraw()

    def values(self, scope='all'):
        keys=CHAT_KEYS if scope=='chat' else MEDIA_CHOICES if scope=='media' else self.variables
        values={k:self.variables[k].get() for k in keys}
        if 'selection' in values:values['selection']=self.model_ids[values['selection']]
        return values

    def _add_missing_selection(self, model_id):
        if model_id not in self.model_ids.values():
            self.model_ids[f'Unavailable · {MODEL_LABELS.get(model_id, model_id)}'] = model_id

    def sync_chat_choice(self):
        """The latest deliberate model/variant change wins; other drafts survive."""
        self._dirty.difference_update(('selection', 'variant_preference'))
        # Force refresh even when a failed UI choice did not change saved policy.
        self.saved_values = {**self.saved_values, 'selection': None}
        self.refresh_saved()

    def _chat_choice_selected(self, key):
        if key == 'variant_preference':
            self.variables[key].set('standard')
            return
        try:
            if self._busy or (callable(getattr(self, 'chat_busy', None)) and self.chat_busy()):
                raise ValueError('Wait for the current chat or Startup before changing models.')
            require_user(self.root_dir, self.account_session)
            from chat_selection import choice_changes
            policy = load_effective_policy(self.root_dir)
            if key == 'selection':
                changes = choice_changes(self.root_dir, policy, selection=self.values('chat')['selection'])
            else:
                changes = choice_changes(self.root_dir, policy,
                    uncensored=self.variables['variant_preference'].get() == 'uncensored')
            save_personal(self.root_dir, changes)
            self.sync_chat_choice()
            self.status.set('Chat size and variant saved; synchronized with chat effort. Applies on the next request.')
            if self.on_save: self.on_save()
        except Exception as exc:
            self.sync_chat_choice()
            self.status.set(f'Not saved: {exc}')

    def _changed(self, key):
        if key in ('variant_preference', 'media_variant'):
            if self.variables[key].get() != 'standard': self.variables[key].set('standard')
            self._dirty.discard(key)
            return
        if self._syncing:return
        value = self.variables[key].get()
        if key == 'selection':value = self.model_ids.get(value, value)
        if value == self.saved_values[key]:self._dirty.discard(key)
        else:self._dirty.add(key)
        scope = 'chat' if key in CHAT_KEYS else 'media'
        self._invalidate_probe(scope)
        self.statuses[scope].set(('Unsaved chat changes. Startup will save and apply them.' if scope == 'chat'
                                 else 'Unsaved media changes. Save to apply to the next job.')
                                if self.dirty(scope) else 'Matches saved settings.')
        if self.on_change:self.on_change()

    def dirty(self, scope='chat'):
        return bool(self._dirty.intersection(CHAT_KEYS if scope == 'chat' else MEDIA_CHOICES))

    def _invalidate_probe(self, scope):
        self._probe_serial[scope] += 1
        # The running probe remains single-flight until its result is drained.

    def refresh_saved(self, models=None, *, policy=None):
        """Refresh clean fields only; preserve local drafts and ignore stale scan policy."""
        current = policy_values(load_effective_policy(self.root_dir) if policy is None else policy)
        if models is not None:
            note = model_inventory_note(models)
            if self.inventory_label.cget('text') != note:self.inventory_label.configure(text=note)
        choices = self._installed_choices if models is None else [(m['label'], m['id']) for m in models if m['installed'] and not m.get('vision_only')]
        if current == self.saved_values and choices == self._installed_choices:return
        before = dict(self.saved_values)
        drafts = self.values()
        chosen = drafts['selection']
        self._syncing = True
        try:
            if models is not None:
                self.model_ids = {'Automatic · fit available memory': 'auto'}
                self.model_ids.update({m['label']: m['id'] for m in models if m['installed'] and not m.get('vision_only')})
                self._installed_choices = choices
            self._add_missing_selection(chosen)
            self._add_missing_selection(current['selection'])
            if tuple(self.selectors['selection'].cget('values')) != tuple(self.model_ids):
                self.selectors['selection'].configure(values=list(self.model_ids))
            for key, value in current.items():
                selected_value = drafts[key] if key in self._dirty else value
                if key == 'selection':
                    selected_value = next(label for label, model_id in self.model_ids.items() if model_id == (chosen if key in self._dirty else value))
                if self.variables[key].get() != selected_value:self.variables[key].set(selected_value)
            self.saved_values = current
            actual = self.values()
            self._dirty = {key for key in self._dirty if actual[key] != current[key]}
        finally:self._syncing = False
        for scope, keys in (('chat', CHAT_KEYS), ('media', MEDIA_CHOICES)):
            if any(before.get(key) != current[key] for key in keys):
                self._invalidate_probe(scope)
                self.statuses[scope].set('Saved settings changed; your unsaved edits are retained.' if self.dirty(scope)
                                         else 'Updated from saved settings.')
        if self.on_change:self.on_change()

    def set_startup_busy(self, busy):
        self._busy = bool(busy)
        for key in CHAT_KEYS:self.selectors[key].configure(state='disabled' if busy else 'readonly')
        self.save_button.configure(state='disabled' if busy or not self.allowed else 'normal')

    def commit_for_startup(self):
        if self._busy:return False
        try:self.refresh_saved()
        except Exception as exc:
            self.status.set(f'Not saved: {exc}')
            return False
        if self.dirty('chat'):return self.save('chat')
        return True

    def startup_summary(self):
        values = self.values('chat')
        name = MODEL_LABELS.get(values['selection'], values['selection']) if values['selection'] != 'auto' else f"Automatic ({values['variant_preference']} first)"
        prefix = 'Pending chat choice' if self.dirty('chat') else 'Saved chat choice'
        return f"{prefix}: {name} · {values['backend']} · context limit {values['context_tokens']}."

    def save(self, scope='chat'):
        if scope == 'chat' and self._busy:return False
        try:
            self.refresh_saved()
            values = self.values(scope)
            save_settings(self.root_dir,values,session=self.account_session,scope=scope)
            self.saved_values.update(values)
            self._dirty.difference_update(values)
            self._invalidate_probe(scope)
            self.statuses[scope].set('Saved. Startup applies this chat choice; active work must finish first.' if scope=='chat' else 'Saved. Media defaults apply to the next job.')
            if self.on_save:self.on_save()
            if self.on_change:self.on_change()
            return True
        except Exception as exc:
            self.statuses[scope].set(f'Not saved: {exc}')
            return False

    def probe(self, scope='chat'):
        if scope in self.probing:return
        self.probing.add(scope);self.statuses[scope].set('Checking current hardware and available memory…')
        self._probe_serial[scope] += 1
        serial = self._probe_serial[scope]
        self.section_buttons[scope][0].configure(state='disabled')
        values=self.values(scope)
        def job():
            try:
                if scope=='media':text=media_fit(self.root_dir,values)
                else:
                    policy=load_effective_policy(self.root_dir)
                    policy.update(selection=values['selection'],backend=values['backend'],context_tokens=int(values['context_tokens']),variant_preference=values['variant_preference'])
                    p=build_plan(self.root_dir,policy=policy);m=p['model']
                    text=f"Current fit: {MODEL_LABELS.get(m['id'],m['id'])} · {p['backend']['backend']} · {m['context_tokens']} tokens · {m['gpu_layers']} GPU layers. Estimate only; running models retain their memory."
            except Exception as exc:text=f'Current fit unavailable: {exc}'
            self.results.put((scope,serial,text))
        threading.Thread(target=job,daemon=True,name='PortalAI-settings-probe').start()

    def poll(self):
        try:
            while True:
                scope,serial,text=self.results.get_nowait();self.probing.discard(scope)
                self.section_buttons[scope][0].configure(state='normal')
                if serial == self._probe_serial[scope]:self.statuses[scope].set(text)
        except queue.Empty:pass
        if self.winfo_exists():self.poll_id=self.after(250 if self.probing else 1000,self.poll)

    def destroy(self):
        if getattr(self,'poll_id',None):
            self.after_cancel(self.poll_id)
            self.poll_id=None
        super().destroy()


def validated_storage(root, policy, values):
    storage = dict(policy.get('storage', {}))
    maximum = shutil.disk_usage(root).total/1024**3
    for key in ('minimum_free_gib', 'output_reserve_gib', 'minimum_free_percent'):
        if key not in values: continue
        number = float(values[key])
        limit = 50 if key == 'minimum_free_percent' else maximum
        if not math.isfinite(number) or not 1 <= number <= limit:
            raise ValueError(f'{key.replace("_", " ")} must be between 1 and {limit:g}.')
        storage['minimum_free_fraction' if key == 'minimum_free_percent' else key] = number/100 if key == 'minimum_free_percent' else number
    return storage


def save_storage_settings(root, values, *, session=None):
    require_admin(root,session)
    policy=load_policy(root)
    policy['storage']=validated_storage(root,policy,values)
    atomic_json(Path(root)/'Agent/hardware_profiles.json',policy)


class StorageReservesPage(tk.Frame):
    def __init__(self,parent,root,colors,on_save=None,*,session=None):
        super().__init__(parent,bg=colors['bg'])
        self.root_dir=Path(root);self.account_session=session;self.on_save=on_save
        self.skin=skin=SettingsSkin(self,colors,compact=True,section_padx=0);skin.remember(self,bg='bg')
        self.variables={};d=inventory(root);policy=d['policy']
        def label(parent,text,*,muted=False):
            result=skin.label(parent,text,muted=muted);result.pack(fill='x',pady=(2,3));return result
        budget=d['storage']; storage_section=skin.section(self, 'Storage reserves')
        self.budget_label = label(storage_section, '')
        self.refresh_budget(budget)
        storage = policy.get('storage', {})
        total_gib = int(shutil.disk_usage(root).total/1024**3)
        for key, title, current, maximum in (
            ('output_reserve_gib', 'Output reserve (disk GiB)', storage.get('output_reserve_gib', 100), total_gib),
            ('minimum_free_gib', 'Minimum free space (disk GiB)', storage.get('minimum_free_gib', 50), total_gib),
            ('minimum_free_percent', 'Minimum free space (% of disk)', storage.get('minimum_free_fraction', .1)*100, 50),
        ):
            var = self.variables[key] = tk.StringVar(self, value=f'{current:g}')
            skin.row(storage_section, title, lambda row, var=var, maximum=maximum:
                     skin.number(row, var, minimum=1, maximum=maximum))
        label(storage_section, 'Floor = larger of GiB or %. Downloads also preserve the output reserve. These are managed disk limits; RAM/VRAM admission stays automatic.', muted=True)

        footer=skin.frame(storage_section);footer.pack(fill='x',pady=(3,0))
        skin.button(footer,'Save storage reserves',self.save,
                    state='normal' if can_admin(root,session) else 'disabled').pack(side='right',pady=0)
        self.status=tk.StringVar(self,value='Saved independently of model settings.')
        skin.label(footer,textvariable=self.status,muted=True).pack(side='left',fill='x',expand=True,padx=(0,12))

    def refresh_budget(self, budget):
        # The existing background status monitor samples disk usage each cycle.
        # Updating the summary must never overwrite unsaved reserve controls.
        text = (f"Free: {budget['free_bytes']/1024**3:.2f} GiB · Outputs: {budget['output_reserve_bytes']/1024**3:.1f} GiB reserved · "
                f"Free-space floor: {budget['minimum_free_bytes']/1024**3:.1f} GiB · Asset budget: {budget['download_budget_bytes']/1024**3:.2f} GiB. "
                'Refreshes with the status monitor (about every 5 seconds), including chat and output writes. '
                'Managed-write checks, not an OS disk quota.')
        if self.budget_label.cget('text') != text:
            self.budget_label.configure(text=text)

    def save(self):
        try:
            save_storage_settings(self.root_dir,{k:v.get() for k,v in self.variables.items()},session=self.account_session)
            self.refresh_budget(storage_budget(self.root_dir))
            self.status.set('Storage reserves saved. Managed writes use the new limits.')
            if self.on_save:self.on_save()
        except Exception as exc:self.status.set(f'Not saved: {exc}')

    def apply_palette(self,colors):self.skin.apply_palette(colors)
