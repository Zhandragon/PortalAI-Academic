"""Read-only PortalAI branding with a tiny, cached rotating portal center."""
import math
from pathlib import Path
import struct
import tkinter as tk
import zlib


def _png(width, height, pixels):
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    rows=b''.join(b'\0'+pixels[y*width*4:(y+1)*width*4] for y in range(height))
    return (b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6,0,0,0))
            +chunk(b'IDAT',zlib.compress(rows,1))+chunk(b'IEND',b''))


class VoiceLogo:
    def __init__(self, master):
        source=Path(__file__).with_name('Branding')/'PortalAI_Emblem_HeroClean_160.png'
        original=tk.PhotoImage(master=master,file=str(source))
        self.base=original.subsample(2)
        width,height=self.base.width(),self.base.height()
        cx,cy=width//2,height//2
        radius=width*.135;side=2*(math.ceil(radius)+1);half=side/2
        # Read the tiny source patch once. No decoding, allocation or rotation
        # takes place in an animation callback, and the source PNG is unchanged.
        pixels={(x,y):self.base.get(x,y) for y in range(cy-side,cy+side+1)
                                         for x in range(cx-side,cx+side+1)}
        self.frames=[]
        for frame in range(24):
            angle=frame*math.tau/24;co,si=math.cos(angle),math.sin(angle);data=bytearray()
            for y in range(side):
                for x in range(side):
                    dx,dy=x-half+.5,y-half+.5;distance=math.hypot(dx,dy)
                    alpha=round(255*max(0,min(1,radius-distance)))
                    if not alpha:data.extend((0,0,0,0));continue
                    sx=cx+dx*co+dy*si;sy=cy-dx*si+dy*co
                    ix,iy=math.floor(sx),math.floor(sy);fx,fy=sx-ix,sy-iy
                    colors=[pixels[(ix,iy)],pixels[(ix+1,iy)],pixels[(ix,iy+1)],pixels[(ix+1,iy+1)]]
                    weights=[(1-fx)*(1-fy),fx*(1-fy),(1-fx)*fy,fx*fy]
                    data.extend((*[round(sum(color[k]*weight for color,weight in zip(colors,weights))) for k in range(3)],alpha))
            self.frames.append(tk.PhotoImage(master=master,data=_png(side,side,bytes(data)),format='png'))
        self.pixel_bytes=4*(width*height+len(self.frames)*side*side)

    def frame(self, angle):
        return self.frames[round(angle/math.tau*len(self.frames))%len(self.frames)]


def cached_logo(widget):
    app=widget.winfo_toplevel()
    if not hasattr(app,'_portalai_voice_logo'):
        app._portalai_voice_logo=VoiceLogo(app)
    return app._portalai_voice_logo
