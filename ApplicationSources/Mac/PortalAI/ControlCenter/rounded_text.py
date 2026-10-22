"""Rounded text containers with ordinary Tk editing and geometry interfaces."""
import tkinter as tk
from ornate_ui import ConnectedBorder, FiligreeScrollbar


class RoundedText(tk.Text):
    def __init__(self,parent,*,palette,scrollbars=False,horizontal=True,**options):
        bg=options.get('bg',palette.get('panel2',palette['panel']))
        self.frame=tk.Frame(parent,bg=bg,bd=0,highlightthickness=0)
        self.background_role=next((key for key in ('model_bg','panel2','panel','bg') if palette.get(key)==bg),'panel2')
        self.foreground_role=next((key for key in ('text','accent2','muted','bad') if palette.get(key)==options.get('fg')),'text')
        options.update(bd=0,relief='flat',highlightthickness=0)
        super().__init__(self.frame,**options)
        self.border=ConnectedBorder(self.frame,palette,radius=10,filigree=False,shine=False)
        self.border.simple=True
        self.border.simple_radius=10
        self.bars=[]
        if scrollbars:
            self.vbar=FiligreeScrollbar(self.frame,command=self.yview,palette=palette,height=1)
            self.vbar.pack(side='right',fill='y',padx=(0,7),pady=8)
            self.configure(yscrollcommand=self.vbar.set);self.bars.append(self.vbar)
            if horizontal:
                from chat_layout import HorizontalFiligreeScrollbar
                bar=HorizontalFiligreeScrollbar(self.frame,command=self.xview,palette=palette)
                bar.pack(side='bottom',fill='x',padx=8,pady=(0,5))
                self.configure(xscrollcommand=bar.set);self.bars.append(bar)
        tk.Text.pack(self,side='left',fill='both',expand=True,padx=8,pady=7)
        # Like ScrolledText, callers lay out the whole field, not its inner text.
        for name in ('pack','pack_configure','pack_forget','pack_info','grid','grid_configure','grid_remove','grid_forget','grid_info','place','place_configure','place_forget','place_info'):
            setattr(self,name,getattr(self.frame,name))

    def apply_palette(self,palette):
        foreground=palette.get(self.foreground_role,palette.get('text','#202224'))
        self.configure(bg=palette.get(self.background_role,palette['panel']),fg=foreground,insertbackground=foreground)
        self.frame.configure(bg=self.cget('bg'))
        self.border.apply_palette(palette)
        for bar in self.bars:bar.apply_palette(palette)
