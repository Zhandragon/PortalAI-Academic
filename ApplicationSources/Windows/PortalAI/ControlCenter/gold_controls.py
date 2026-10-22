"""Gold native ttk sliders and increment fields, independent of Windows theme."""
import itertools
import tkinter as tk
from tkinter import ttk
from elegant_native_ui import blend
from rounded_controls import image_element, field_style
from ui_style_cache import cached_style

_IDS=itertools.count()


def elements(style):
    for source in ('Horizontal.Scale.trough','Horizontal.Scale.slider','Spinbox.field','Spinbox.uparrow','Spinbox.downarrow'):
        name='PortalGold.'+source
        if name not in style.element_names():style.element_create(name,'from','clam',source)


class GoldScale(ttk.Scale):
    def __init__(self,parent,*,palette,from_=0,to=100,resolution=1,variable=None,command=None,length=180):
        self.minimum,self.maximum,self.step=float(from_),float(to),float(resolution)
        self.callback=command;self._moving=False
        self.style_name=f'PortalGold{next(_IDS)}.Horizontal.TScale'
        super().__init__(parent,from_=from_,to=to,variable=variable,command=self._changed,
                         orient='horizontal',length=length,takefocus=True,style=self.style_name)
        self.apply_palette(palette)
        for event, direction in (('<Left>',-1),('<Down>',-1),('<Right>',1),('<Up>',1)):
            self.bind(event,lambda _event,d=direction:self._key_step(d))
        self.bind('<Home>',lambda _event:self._key_value(self.minimum))
        self.bind('<End>',lambda _event:self._key_value(self.maximum))

    def _key_value(self,value):
        if not self.instate(['disabled']):self.set(value)
        return 'break'

    def _key_step(self,direction):
        return self._key_value(self.get()+direction*self.step)

    def _quantize(self,value):
        value=float(value)
        return max(self.minimum,min(self.maximum,self.minimum+round((value-self.minimum)/self.step)*self.step))

    def _changed(self,value):
        if self._moving:return
        self._moving=True
        try:
            number=self._quantize(value)
            if float(value)!=number:super().set(number)
            if self.callback:self.callback(str(number))
        finally:self._moving=False

    def set(self,value):
        super().set(self._quantize(value))

    def apply_palette(self,p):
        gold=p.get('gold_mid',p.get('gold','#A87D32'));shine=p.get('gold_shine',p.get('tool','#D9BE78'))
        style=ttk.Style(self)
        # Image borders preserve rounded pixels; they are not travel padding.
        trough=image_element(self,blend(gold,p['panel'],.72),gold,suffix='trough',radius=6,width=28,height=12,border=(6,6,6,6),padding=0)
        thumb=image_element(self,gold,shine,suffix='slider',radius=7,width=20,height=20,border=(7,7,7,7))
        bg=self.master.cget('bg');accent=p.get('accent',p.get('cyan',gold))
        def build(style,name):
            style.layout(name,[('null',{'sticky':'we','children':[(trough,{'sticky':'we'}),(thumb,{'side':'left','sticky':''})]})])
            style.configure(name,background=bg,bordercolor=gold,troughcolor=blend(gold,p['panel'],.72),
                            lightcolor=shine,darkcolor=gold,sliderlength=19,gripcount=1)
            style.map(name,background=[],bordercolor=[('focus',accent)])
        self.style_name=cached_style(self,'Gold.Horizontal.TScale',(trough,thumb,bg,gold,shine,accent,p['panel']),build)
        if self.cget('style')!=self.style_name:self.configure(style=self.style_name)


class GoldSpinbox(ttk.Spinbox):
    def __init__(self,parent,*,palette,**kwargs):
        self.style_name=f'PortalGold{next(_IDS)}.TSpinbox'
        self._rounded_style=self.style_name
        super().__init__(parent,style=self.style_name,**kwargs)
        self.apply_palette(palette)

    def apply_palette(self,p):
        field_style(self,p,'Spinbox')
        self.style_name=self._rounded_style
