"""Lightweight Tk workflow canvas; no web engine or extra runtime."""
import tkinter as tk
from workflows import validate


def connect(draft,source,target,port='next'):
    """Validate routing before changing the editor's draft; cycles stay forbidden."""
    import copy
    candidate=copy.deepcopy(draft);step=next(s for s in candidate['steps'] if s['id']==source)
    if port not in (('then','else') if step['kind']=='condition' else ('next',)):raise ValueError('Choose a compatible output port')
    step[port]=target;validate(candidate)
    draft['steps']=candidate['steps']


class WorkflowCanvas(tk.Frame):
    def __init__(self,parent,draft,colors,select,invoke):
        super().__init__(parent,bg=colors['panel']);self.draft=draft;self.select=select;self.invoke=invoke;self.drag=None;self.link=None;self.positions={};self.colors=colors;self.pending_draw=None
        self.canvas=tk.Canvas(self,height=210,bg=colors.get('bg',colors['panel']),highlightthickness=0,scrollregion=(0,0,1800,1800))
        sx=tk.Scrollbar(self,orient='horizontal',command=self.canvas.xview);sy=tk.Scrollbar(self,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=sx.set,yscrollcommand=sy.set);self.canvas.grid(row=0,column=0,sticky='nsew');sx.grid(row=1,column=0,sticky='ew');sy.grid(row=0,column=1,sticky='ns')
        self.columnconfigure(0,weight=1);self.rowconfigure(0,weight=1)
        self.canvas.bind('<ButtonPress-1>',self.press);self.canvas.bind('<B1-Motion>',self.motion);self.canvas.bind('<ButtonRelease-1>',self.release)
        self.canvas.bind('<Escape>',lambda e:self.cancel_link());self.canvas.bind('<Button-3>',lambda e:self.cancel_link())
        self.redraw()
    def cancel_link(self):self.link=None;self.redraw()
    def redraw(self):
        if self.pending_draw is not None:self.after_cancel(self.pending_draw);self.pending_draw=None
        c=self.canvas;c.delete('all');steps=self.draft['steps'];layout=self.draft.setdefault('layout',{});ids={s['id'] for s in steps}
        for obsolete in set(layout)-ids:layout.pop(obsolete)
        self.positions={s['id']:layout.get(s['id'],[35+(i%3)*250,35+(i//3)*115]) for i,s in enumerate(steps)}
        for i,s in enumerate(steps):
            x,y=self.positions[s['id']]
            ports=('then','else') if s['kind']=='condition' else ('next',)
            for j,port in enumerate(ports):
                target=s.get(port,steps[i+1]['id'] if i+1<len(steps) else 'end');py=y+25+j*25
                if target in self.positions:
                    tx,ty=self.positions[target];c.create_line(x+185,py,x+210,py,tx-15,ty+30,tx,ty+30,fill='#45d9d1' if port!='else' else '#caa664',arrow='last',smooth=True,width=2)
                elif target=='end':c.create_text(x+215,py,text='end',fill='#caa664',anchor='w')
        for i,s in enumerate(steps):
            x,y=self.positions[s['id']];tag='node:'+s['id']
            c.create_rectangle(x,y,x+185,y+75,fill=self.colors['panel'],outline='#caa664',width=2,tags=(tag,))
            c.create_text(x+10,y+16,text=str(i+1)+'. '+s['id'],fill=self.colors['text'],anchor='w',tags=(tag,))
            c.create_text(x+10,y+40,text=s['kind'],fill='#45d9d1',anchor='w',tags=(tag,))
            ports=('then','else') if s['kind']=='condition' else ('next',)
            for j,port in enumerate(ports):
                py=y+25+j*25;pt='port:'+s['id']+':'+port
                c.create_oval(x+178,py-6,x+190,py+6,fill='#45d9d1' if port!='else' else '#caa664',outline='',tags=(pt,))
                if port!='next':c.create_text(x+172,py,text=port,fill=self.colors['text'],anchor='e',tags=(pt,))
        bounds=c.bbox('all') or (0,0,800,300);c.configure(scrollregion=(min(0,bounds[0]-30),min(0,bounds[1]-30),bounds[2]+40,bounds[3]+40))
        if self.link:c.create_text(10,10,text='Choose a later destination node; Esc cancels.',fill='#45d9d1',anchor='nw')
    def press(self,event):
        self.canvas.focus_set();tags=self.canvas.gettags('current')
        port=next((t for t in tags if t.startswith('port:')),None)
        if port:
            _,sid,key=port.split(':');self.link=(sid,key);self.redraw();return
        node=next((t[5:] for t in tags if t.startswith('node:')),None)
        if not node:return
        if self.link:
            source,key=self.link
            def finish():
                connect(self.draft,source,node,key);self.link=None;self.redraw()
                self.select(next(i for i,s in enumerate(self.draft['steps']) if s['id']==source))
            self.invoke(finish);return
        self.select(next(i for i,s in enumerate(self.draft['steps']) if s['id']==node))
        x,y=self.positions[node];self.drag=(node,self.canvas.canvasx(event.x)-x,self.canvas.canvasy(event.y)-y)
    def motion(self,event):
        if not self.drag:return
        sid,dx,dy=self.drag
        self.draft.setdefault('layout',{})[sid]=[max(-10000,min(10000,round(self.canvas.canvasx(event.x)-dx))),max(-10000,min(10000,round(self.canvas.canvasy(event.y)-dy)))]
        if self.pending_draw is None:self.pending_draw=self.after(16,self.redraw)
    def release(self,event):self.drag=None
    def destroy(self):
        if self.pending_draw is not None:self.after_cancel(self.pending_draw);self.pending_draw=None
        super().destroy()
