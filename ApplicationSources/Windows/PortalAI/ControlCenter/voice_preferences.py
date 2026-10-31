"""Staged voice model controls shared by voice and effort preference pages."""
import tkinter as tk
from voice_policy import LABELS,preferences,resolve,effort_for_voice


class VoicePreferences:
    def __init__(self,panel,skin,parent,effort_draft=None):
        self.panel=panel;self.effort_draft=effort_draft;self.guard=False
        pref=preferences(panel.settings)
        self.model=tk.StringVar(parent,value=LABELS[pref['tts_model']])
        self.linked=tk.BooleanVar(parent,value=pref['tts_link_effort'])
        self.labels=[];self._build(skin,parent)
        self.model.trace_add('write',self._model_changed)
        self.linked.trace_add('write',self._model_changed)
        if effort_draft is not None:effort_draft['chat'].trace_add('write',self._effort_changed)
        self.refresh()

    def _build(self,skin,parent):
        skin.row(parent,'Voice model',lambda row:skin.combo(row,self.model,list(LABELS.values())))
        skin.check(parent,'Link voice to effort (turn off for independent TTS)',self.linked)
        skin.label(parent,'Linked: Fast favors the lightweight voice; Balanced/Deep favor expressive Qwen when supported. Changing a manual voice choice also adjusts effort. Unlink to keep the voice independent of the LLM. Automatic follows hardware and this link setting. Changes apply to the next spoken reply.',muted=True).pack(fill='x',pady=4)
        label=skin.label(parent,'',muted=True);label.pack(fill='x',pady=4);self.labels.append(label)

    def add_mirror(self,skin,parent):self._build(skin,parent);self.refresh()

    def values(self):
        reverse={label:key for key,label in LABELS.items()}
        return preferences({'tts_model':reverse.get(self.model.get(),''),'tts_link_effort':bool(self.linked.get())})

    def _model_changed(self,*unused):
        if self.guard:return
        self.guard=True
        try:
            pref=self.values()
            if pref['tts_link_effort'] and self.effort_draft is not None:
                current=self.effort_draft['chat'].get()
                self.effort_draft['chat'].set(effort_for_voice(pref['tts_model'],current))
        finally:self.guard=False
        self.refresh()

    def _effort_changed(self,*unused):
        if self.guard:return
        self.guard=True
        try:
            if self.linked.get() and self.values()['tts_model']!='auto':
                self.model.set(LABELS['piper' if self.effort_draft['chat'].get()=='fast' else 'qwen'])
        finally:self.guard=False
        self.refresh()

    def refresh(self):
        effort=getattr(self.panel,'effort',None);capacity=(getattr(effort,'capability_data',None) or {}).get('voice')
        level=self.effort_draft['chat'].get() if self.effort_draft is not None else getattr(effort,'profile','balanced')
        if capacity:
            try:
                row=resolve(self.values(),level,capacity)
                text='Voice preview: '+row['label']+'. '+row['selection_reason']+'. Free memory is checked again before loading.'
            except (ValueError,RuntimeError) as exc:text=str(exc)
        else:text='Voice hardware scan pending. Use Refresh hardware check in Effort & continuation.'
        for label in self.labels:
            try:label.configure(text=text)
            except tk.TclError:pass

    def validated_values(self):
        pref=self.values();effort=getattr(self.panel,'effort',None)
        capacity=(getattr(effort,'capability_data',None) or {}).get('voice')
        if pref['tts_model']!='auto':
            if not capacity:raise ValueError('Refresh the hardware check before selecting a manual voice model.')
            resolve(pref,self.effort_draft['chat'].get() if self.effort_draft else getattr(effort,'profile','balanced'),capacity)
        return pref
