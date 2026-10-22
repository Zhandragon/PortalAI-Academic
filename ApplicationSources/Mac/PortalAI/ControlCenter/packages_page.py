"""Compact package inventory with adaptive columns and separate weight lists."""
import tkinter as tk
from settings_style import SettingsSkin
from ornate_ui import ConnectedBorder
from rounded_text import RoundedText
from ui_extensions import ResponsiveFlow
from portal_frontend_v15136 import portal_display_font


class PackagesView(tk.Frame):
    def __init__(self,parent,colors):
        super().__init__(parent,bg=colors['panel'])
        self.skin=skin=SettingsSkin(self,colors);skin.remember(self,bg='panel')
        self.entries=[];self.page_index=0;self.page_size=12;self.selected='packages';self.pending=None
        self._layout_signature=None
        self.measure=tk.Canvas(self,highlightthickness=0)
        self.tabs={};bar=ResponsiveFlow(self,bg=colors['panel']);skin.remember(bar,bg='panel');bar.pack(fill='x',pady=(0,6))
        for key,title in (('packages','Packages'),('weights','Weights & LoRAs')):
            self.tabs[key]=bar.add(skin.button(bar,title,lambda key=key:self.select(key)))
            self.tabs[key].configure(font=(portal_display_font(bar),9,'bold'))
        self.host=skin.frame(self);self.host.pack(fill='both',expand=True)
        self.catalog=skin.frame(self.host);self.weights=skin.frame(self.host)
        search=skin.frame(self.catalog);search.pack(fill='x',pady=(0,6))
        skin.label(search,'Find a package',muted=True,width=0).pack(side='left',padx=(0,10))
        self.query=tk.StringVar(self)
        field=skin.entry(search,'');field.configure(textvariable=self.query);field.pack(side='left',fill='x',expand=True)
        self.query.trace_add('write',self.filter)
        footer=skin.frame(self.catalog);footer.pack(side='bottom',fill='x',pady=(6,0))
        self.previous=skin.button(footer,'Previous',lambda:self.turn(-1));self.previous.pack(side='left')
        self.next=skin.button(footer,'Next',lambda:self.turn(1));self.next.pack(side='right')
        self.counter=skin.label(footer,'',muted=True);self.counter.pack(side='left',fill='x',expand=True,padx=12)
        # The body scrolls at very small sizes; paging keeps the standard viewport
        # complete without a long wall of installed entries.
        self.viewport=skin.frame(self.catalog);self.viewport.pack(fill='both',expand=True)
        self.cards=skin.scrolling_body(self.viewport)
        self.viewport.bind('<Configure>',self.queue_layout,add='+')
        self.catalog.bind('<Map>',self.queue_layout,add='+')
        self.weight_boxes=[]
        for title,height in (('Image/video models · checkpoints and diffusion weights',11),('Installed LoRAs · compatible base model required',5)):
            skin.label(self.weights,title,muted=True,font=('Segoe UI',9,'bold')).pack(fill='x',pady=(6,5))
            box=RoundedText(self.weights,palette=colors,scrollbars=True,height=height,wrap='none',state='disabled',font=('Consolas',9),bg=colors.get('model_bg',colors['panel2']),fg=colors['text'])
            box.pack(fill='both',expand=True,pady=(0,8));self.weight_boxes.append(box);skin.gold_controls.append(box)
        self.diffusion_box,self.lora_box=self.weight_boxes
        self.select('packages')

    def add(self,key,title):
        skin=self.skin;card=skin.frame(self.cards,surface='card' if 'card' in skin.colors else 'panel')
        border=ConnectedBorder(card,skin.colors,radius=10,filigree=False);border.simple=True;border.simple_radius=10;skin.borders.append(border)
        heading=skin.frame(card,surface='card' if 'card' in skin.colors else 'panel');heading.pack(fill='x',padx=10,pady=(8,2))
        surface='card' if 'card' in skin.colors else 'panel'
        status=skin.label(heading,'CHECKING',surface=surface,font=('Segoe UI',8,'bold'),width=12);status.pack(side='right')
        caption=skin.label(heading,title,surface=surface,font=('Segoe UI',9,'bold'));caption.pack(side='left',fill='x',expand=True)
        card.caption=caption
        detail=skin.label(card,'Awaiting detection…',surface=surface,muted=True);detail.pack(fill='x',padx=10,pady=(0,8))
        self.entries.append((key,title,card,status,detail));self.queue_layout()
        return status,detail

    def select(self,key):
        self.selected=key;self.catalog.pack_forget();self.weights.pack_forget()
        (self.catalog if key=='packages' else self.weights).pack(fill='both',expand=True)
        self.apply_palette(self.skin.colors);self.queue_layout()

    def filter(self,*_):self.page_index=0;self.queue_layout()
    def turn(self,direction):self.page_index=max(0,self.page_index+direction);self.queue_layout()
    def queue_layout(self,*_):
        if self.pending is None:self.pending=self.after_idle(self.layout)
    def layout(self):
        self.pending=None
        if self.selected!='packages' or not self.viewport.winfo_ismapped():return
        cols=2 if self.viewport.winfo_width()>=980 else 1
        query=self.query.get().strip().casefold()
        signature=(self.viewport.winfo_width(),self.viewport.winfo_height(),query,self.page_index,
            tuple((key,card.caption.cget('text'),str(card.caption.cget('font')),str(detail.cget('font')),detail.cget('text'),
                   status.winfo_reqwidth(),status.winfo_reqheight()) for key,title,card,status,detail in self.entries))
        if signature==self._layout_signature:return
        entries=[entry for entry in self.entries if query in (entry[1]+' '+entry[4].cget('text')).casefold()]
        width=max(100,(self.viewport.winfo_width()-22-6*(cols-1))//cols-24)
        def text_height(widget,limit):
            item=self.measure.create_text(0,0,anchor='nw',text=widget.cget('text'),font=widget.cget('font'),width=max(40,limit))
            box=self.measure.bbox(item);self.measure.delete(item)
            return box[3]-box[1] if box else 16
        chunks=[];current=[];height=0;available=max(60,self.viewport.winfo_height()-10)
        for start in range(0,len(entries),cols):
            row=entries[start:start+cols]
            row_height=max(max(text_height(e[2].caption,width-e[3].winfo_reqwidth()),e[3].winfo_reqheight())+text_height(e[4],width)+32 for e in row)
            if current and height+row_height>available:chunks.append(current);current=[];height=0
            current.extend(row);height+=row_height
        if current:chunks.append(current)
        if not chunks:chunks=[[]]
        pages=len(chunks);self.page_index=min(self.page_index,pages-1)
        visible=chunks[self.page_index];self.page_size=len(visible)
        for entry in self.entries:entry[2].grid_forget()
        self.cards.columnconfigure(0,weight=1,uniform='package');self.cards.columnconfigure(1,weight=1 if cols==2 else 0,uniform='package' if cols==2 else '')
        for index,entry in enumerate(visible):
            entry[2].grid(row=index//cols,column=index%cols,sticky='nsew',padx=(0,6) if cols==2 and index%2==0 else (0,0),pady=(0,6))
        self.counter.configure(text=f'{len(entries)} packages · Page {self.page_index+1} of {pages}')
        self.previous.configure(state='normal' if self.page_index else 'disabled');self.next.configure(state='normal' if self.page_index<pages-1 else 'disabled')
        self.skin.canvas.yview_moveto(0)
        self._layout_signature=signature[:3]+(self.page_index,)+signature[4:]
    def apply_palette(self,colors):
        self.skin.apply_palette(colors)
        for key,button in self.tabs.items():button.configure(bg=colors['gold_mid'] if key==self.selected else colors['button'])
        for _,_,_,status,_ in self.entries:
            value=status.cget('text')
            role='good' if value in ('INSTALLED','READY') else 'bad' if value in ('MISSING','NOT INSTALLED','ERROR') else 'warn'
            status.configure(fg=colors.get(role,colors['text']))
