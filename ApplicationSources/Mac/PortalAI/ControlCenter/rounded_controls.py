"""Rounded native ttk fields; selection, editing and keyboard behavior stay native."""
import base64
import ctypes
import itertools
import os
import tkinter as tk
from tkinter import ttk
from elegant_native_ui import _round_png, blend
from ui_style_cache import cached_style

_IDS=itertools.count()

def arrow_element(widget,color,part):
    app=widget.winfo_toplevel()
    cache=getattr(app,'_portalai_arrow_elements',None)
    if cache is None: cache=app._portalai_arrow_elements={}
    key=(ttk.Style(widget).theme_use(),color,part)
    if key not in cache:
        photo=tk.PhotoImage(master=widget,width=16,height=11)
        for y in range(4):
            span=3-y if part=='downarrow' else y
            photo.put(color,to=(7-span,3+y,8+span,4+y))
        name=f'PortalArrow{next(_IDS)}.{part}'
        ttk.Style(widget).element_create(name,'image',photo)
        cache[key]=(name,photo)
    return cache[key][0]

def image_element(widget,fill,edge,*,suffix='field',radius=8,width=32,height=28,border=(9,9,9,9),padding=None):
    app=widget.winfo_toplevel()
    cache=getattr(app,'_portalai_round_elements',None)
    if cache is None:cache=app._portalai_round_elements={}
    key=(ttk.Style(widget).theme_use(),fill,edge,suffix,radius,width,height,border,padding)
    if key not in cache:
        photo=tk.PhotoImage(master=widget,data=base64.b64encode(_round_png(fill,edge,'#000000',
            radius=radius,width=width,height=height)),format='png')
        name=f'PortalRound{next(_IDS)}.{suffix}'
        options = {} if padding is None else {'padding': padding}
        ttk.Style(widget).element_create(name,'image',photo,border=border,sticky='nswe',**options)
        cache[key]=(name,photo)
    return cache[key][0]


def field_style(widget,palette,kind):
    p=palette;style=ttk.Style(widget)
    gold=p.get('gold_mid',p.get('gold','#A87D32'))
    field=image_element(widget,p['panel2'],gold)
    if kind=='Entry':children=[('Entry.padding',{'sticky':'nswe','children':[('Entry.textarea',{'sticky':'nswe'})]})]
    else:
        arrows=[(arrow_element(widget,gold,part),{'side':side,'sticky':'e'}) for part,side in
                ([('downarrow','top')] if kind=='Combobox' else [('uparrow','top'),('downarrow','bottom')])]
        children=[('null',{'side':'right','children':arrows}),
                  (f'{kind}.padding',{'sticky':'nswe','children':[(f'{kind}.textarea',{'sticky':'nswe'})]})]
    try:bg=widget.master.cget('bg')
    except tk.TclError:bg=p['panel']
    signature=(field,bg,p['panel2'],p['text'],gold,p.get('muted',p['text']),p.get('accent',gold))
    def build(style,name):
        style.layout(name,[(field,{'sticky':'nswe','children':children})])
        style.configure(name,background=bg,fieldbackground=p['panel2'],foreground=p['text'],
            insertcolor=p['text'],bordercolor=gold,arrowcolor=gold,arrowsize=12,padding=(1,0))
        style.map(name,fieldbackground=[('readonly',p['panel2'])],foreground=[('disabled',p.get('muted',p['text'])),('readonly',p['text'])],
            selectbackground=[('readonly',p.get('accent',gold))],selectforeground=[('readonly',p['text'])])
    name=cached_style(widget,'Round.T'+kind,signature,build)
    widget._rounded_style=name
    if widget.cget('style')!=name:widget.configure(style=name)


class RoundedEntry(ttk.Entry):
    def __init__(self,parent,*,palette,**kwargs):
        self._rounded_style=f'PortalRoundEntry{next(_IDS)}.TEntry'
        super().__init__(parent,style=self._rounded_style,**kwargs)
        self.apply_palette(palette)

    def apply_palette(self,palette):field_style(self,palette,'Entry')


class RoundedCombobox(ttk.Combobox):
    def __init__(self,parent,*,palette,**kwargs):
        self._rounded_style=f'PortalRoundCombo{next(_IDS)}.TCombobox'
        self._popup_after=None
        super().__init__(parent,style=self._rounded_style,**kwargs)
        self.configure(postcommand=self._prepare_popup)
        self.bind('<Destroy>',self._destroyed,add='+')
        self.apply_palette(palette)

    def apply_palette(self,palette):
        self.palette=dict(palette);field_style(self,palette,'Combobox')
        self._paint_popup()

    def _paint_popup(self):
        p=self.palette;style=ttk.Style(self)
        prior=getattr(self,'popup_path',None)
        existed=bool(prior and int(self.tk.call('winfo','exists',prior)))
        popup=str(self.tk.call('ttk::combobox::PopdownWindow',str(self)))
        edge=p.get('gold_mid',p.get('gold','#A87D32'))
        signature=(style.theme_use(),p['panel2'],p['panel'],p['text'],edge,p.get('accent',edge))
        if existed and signature==getattr(self,'_popup_palette_signature',None):return
        field=image_element(self,p['panel2'],edge)
        def build(style,name):
            style.layout(name,[(field,{'sticky':'nswe'})])
            style.configure(name,background=p['panel'],borderwidth=0)
        frame_style=cached_style(self,'Popup.TFrame',(field,p['panel']),build)
        self.tk.call(popup+'.f','configure','-style',frame_style,'-padding',7)
        self.tk.call(popup+'.f.l','configure','-background',p['panel2'],'-foreground',p['text'],
            '-selectbackground',p.get('accent',edge),'-selectforeground',p['text'],
            '-highlightthickness',0,'-borderwidth',0)
        self.popup_path=popup
        self._popup_palette_signature=signature

    def _prepare_popup(self):
        self._paint_popup()
        if self._popup_after is not None:self.after_cancel(self._popup_after)
        self._popup_after=self.after_idle(self._round_popup)

    def _round_popup(self):
        self._popup_after=None
        if os.name!='nt':return
        from ctypes import wintypes as w
        user=ctypes.WinDLL('user32',use_last_error=True);gdi=ctypes.WinDLL('gdi32',use_last_error=True)
        user.GetAncestor.argtypes=[w.HWND,w.UINT];user.GetAncestor.restype=w.HWND
        user.SetWindowRgn.argtypes=[w.HWND,w.HANDLE,w.BOOL];user.SetWindowRgn.restype=ctypes.c_int
        gdi.CreateRoundRectRgn.argtypes=[ctypes.c_int]*6;gdi.CreateRoundRectRgn.restype=w.HANDLE
        gdi.DeleteObject.argtypes=[w.HANDLE]
        pop=self.popup_path
        width=int(self.tk.call('winfo','width',pop));height=int(self.tk.call('winfo','height',pop))
        hwnd=user.GetAncestor(int(str(self.tk.call('winfo','id',pop)),0),2)
        region=gdi.CreateRoundRectRgn(0,0,width+1,height+1,16,16)
        if region and not user.SetWindowRgn(hwnd,region,True):gdi.DeleteObject(region)

    def _destroyed(self,event):
        if event.widget is self and self._popup_after is not None:
            self.after_cancel(self._popup_after);self._popup_after=None
