"""Keyboard-accessible Help contents with quiet gold row dividers."""
import tkinter as tk


class TopicList(tk.Canvas):
    def __init__(self,parent,colors):
        super().__init__(parent,bd=0,highlightthickness=0,takefocus=True,width=210)
        self.colors=colors;self.items=[];self.selected=None;self.bounds=[]
        self.bind('<Configure>',lambda _:self._draw())
        self.bind('<Button-1>',self._click)
        for key,step in (('Up',-1),('Down',1),('Prior',-6),('Next',6)):
            self.bind('<'+key+'>',lambda _,step=step:self._move(step))
        self.bind('<Home>',lambda _:self._select(0))
        self.bind('<End>',lambda _:self._select(len(self.items)-1))
        self.bind('<Return>',lambda _:self.event_generate('<<ListboxSelect>>'))
        self.bind('<MouseWheel>',lambda e:self._wheel(-1 if e.delta>0 else 1))
        self.bind('<Button-4>',lambda _:self._wheel(-1))
        self.bind('<Button-5>',lambda _:self._wheel(1))
        self.apply_palette(colors)

    def _wheel(self,step):self.yview_scroll(step*2,'units');return 'break'
    def delete(self,first,last=None):
        if first==0 and last=='end':self.items=[];self.selected=None;self._draw()
        else:super().delete(first)
    def insert(self,index,text):self.items.append(str(text));self._draw()
    def curselection(self):return () if self.selected is None else (self.selected,)
    def selection_clear(self,*_):self.selected=None;self._draw()
    def selection_set(self,index):self.selected=int(index);self._draw()
    def activate(self,index):pass
    def see(self,index):
        if not 0<=index<len(self.bounds):return
        top,bottom=self.bounds[index];visible=self.canvasy(0);height=self.winfo_height()
        total=max(1,self.bounds[-1][1])
        if top<visible:self.yview_moveto(top/total)
        elif bottom>visible+height:self.yview_moveto(max(0,bottom-height)/total)
    def _move(self,step):
        if self.selected is None:return self._select(0 if step>0 else len(self.items)-1)
        return self._select(max(0,min(len(self.items)-1,self.selected+step)))
    def _select(self,index):
        if 0<=index<len(self.items):
            self.selection_set(index);self.see(index);self.event_generate('<<ListboxSelect>>')
        return 'break'
    def _click(self,event):
        self.focus_set();y=self.canvasy(event.y)
        for index,(top,bottom) in enumerate(self.bounds):
            if top<=y<bottom:return self._select(index)
    def apply_palette(self,colors):self.colors=colors;self.configure(bg=colors['panel']);self._draw()
    def _draw(self):
        super().delete('all');self.bounds=[]
        width=max(80,self.winfo_width());y=0;p=self.colors
        for index,title in enumerate(self.items):
            active=index==self.selected
            text=self.create_text(10,y+9,text=title,anchor='nw',width=width-22,
                font=('Segoe UI',9,'bold' if active else 'normal'),fill='#FFFFFF' if active else p.get('muted',p['text']))
            box=self.bbox(text);height=max(34,(box[3]-box[1] if box else 16)+18)
            if active:
                background=self.create_rectangle(3,y+2,width-4,y+height-2,fill=p.get('accent','#3E91A2'),outline='')
                self.tag_lower(background,text)
            self.create_line(10,y+height-1,width-12,y+height-1,fill=p.get('gold_mid','#A87D32'))
            self.bounds.append((y,y+height));y+=height
        self.configure(scrollregion=(0,0,width,max(1,y)),yscrollincrement=18)
