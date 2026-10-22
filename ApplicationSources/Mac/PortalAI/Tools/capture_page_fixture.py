"""Compose PrintWindow renders of the fixture and its own passive watermark.

No desktop pixels or other applications are captured. The result is an explicit
render composite: Windows does not include separate layered HWNDs in PrintWindow.
"""
import struct
import zlib
from smoke_account_panels import capture_window


def read_render(path):
    data=path.read_bytes();width,height=struct.unpack('>II',data[16:24]);offset=8;compressed=b''
    assert data[24:26]==bytes((8,2))
    while offset<len(data):
        size=int.from_bytes(data[offset:offset+4],'big');tag=data[offset+4:offset+8]
        if tag==b'IDAT':compressed+=data[offset+8:offset+8+size]
        offset+=size+12
    raw=zlib.decompress(compressed);rows=[]
    for y in range(height):
        start=y*(width*3+1);assert raw[start]==0
        rows.append(raw[start+1:start+1+width*3])
    return width,height,bytearray(b''.join(rows))


def capture_page(app,mark,path):
    assert mark.app is app and mark.win.master is app and mark.shown
    base=path.with_stem(path.stem+'-window');overlay=path.with_stem(path.stem+'-watermark-layer')
    capture_window(app,base);capture_window(mark.win,overlay)
    width,height,pixels=read_render(base);mw,mh,layer=read_render(overlay)
    ox=mark.win.winfo_rootx()-app.winfo_rootx();oy=mark.win.winfo_rooty()-app.winfo_rooty()
    alpha=float(mark.win.attributes('-alpha'));assert 0<alpha<=(1 if mark.selected_getter()=='help' else .22)
    photo=mark.images[mark.key]
    rgba = None
    if mark.selected_getter() == 'help':
        from alpha_watermark import premultiplied_bgra
        mw, mh, rgba = premultiplied_bgra(photo)
    for y in range(mh):
        for x in range(mw):
            if not (0<=ox+x<width and 0<=oy+y<height):continue
            source=(y*mw+x)*3;color=layer[source:source+3]
            if rgba is not None:
                p=(y*mw+x)*4
                b,g,r,a=rgba[p:p+4];color=(r,g,b);alpha=a/255
            # PrintWindow emits black for fully transparent image pixels. Use the
            # actual Tk image mask, never a guessed RGB background from that DC.
            if photo.transparency_get(x,y):continue
            target=((oy+y)*width+ox+x)*3
            for channel in range(3):pixels[target+channel]=min(255, round((color[channel] if rgba is not None else alpha*color[channel])+(1-alpha)*pixels[target+channel]))
    rows=b''.join(b'\0'+pixels[y*width*3:(y+1)*width*3] for y in range(height))
    def chunk(tag,data):return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data)&0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+
        chunk(b'IDAT',zlib.compress(rows))+chunk(b'IEND',b''))
