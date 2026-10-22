"""macOS 14+ owned-window capture. Native input stays inside the Tk capability.

ScreenCaptureKit's independent-window filter cannot include another app. Match
the authenticated Tk client rectangle to exactly one window of the verified PID;
never interpret Tk's opaque winfo ID as a CGWindowID or capture a display region.
"""
import math
import os
from pathlib import Path
import platform
import threading

from linux_desktop import Desktop as InputTransport


def rect_tuple(rect):
    return (float(rect.origin.x),float(rect.origin.y),float(rect.size.width),float(rect.size.height))


def client_crop(window,outer):
    x,y,w,h=outer
    if any(not math.isfinite(v) for v in outer):raise ValueError('Invalid Mac window bounds')
    rx,ry,width,height=(window[k] for k in ('rootx','rooty','width','height'))
    if any(type(v) is not int for v in (rx,ry,width,height)):raise ValueError('Update the PortalAI Mac input adapter')
    if not 1<=width<=2560 or not 1<=height<=1600:raise ValueError('Resize PortalAI below 2560 x 1600')
    # Aqua client width excludes at most a small frame border; titlebar above
    # the client is allowed. Fail closed on ambiguous/partial/oversized matches.
    dx,dy=rx-x,ry-y
    if not (0<=dx<=4 and 0<=w-width<=8 and 0<=dy<=80 and 0<=h-height-dy<=4):
        raise ValueError('Mac window does not match the owned Tk client')
    if any(abs(v-round(v))>.05 for v in (dx,dy,w,h)):raise ValueError('Nonintegral Mac window geometry')
    return (round(dx),round(dy),width,height)


def choose_window(window,entries):
    matches=[]
    for entry in entries:
        app=entry.owningApplication()
        if app is None or int(app.processID())!=window['pid'] or not entry.isOnScreen():continue
        # Borderless Aqua windows may have no native title. PID plus a unique
        # exact client geometry is required; title text is never an identity.
        try:crop=client_crop(window,rect_tuple(entry.frame()))
        except (KeyError,ValueError):continue
        matches.append((entry,crop))
    if len(matches)!=1:raise RuntimeError('Owned Mac window is missing or ambiguous; close native sheets locally and refresh')
    return matches[0]


def completed_call(start,timeout=7):
    done=threading.Event();result=[]
    def callback(value,error):
        result[:]=[value,error];done.set()
    start(callback)
    if not done.wait(timeout):raise TimeoutError('macOS window capture timed out')
    if result[1] is not None or result[0] is None:raise RuntimeError('macOS refused window capture; check Screen Recording permission')
    return result[0]


class Desktop(InputTransport):
    def __init__(self,manager):
        if int(platform.mac_ver()[0].split('.')[0] or 0)<14:raise RuntimeError('Mac projection requires macOS 14 or newer')
        self.manager=manager;self.u=self;self.lock=threading.Lock()

    def validate(self,window):
        from macos_process import identity
        row=identity(window['pid'])
        if (row['uid']!=os.getuid() or int(row['create_time']*1_000_000)!=window['start'] or
                row['executable']!=window['executable'] or
                Path(row['executable']).resolve()!=(self.manager.root/'Runtime/MacPython/bin/python3.12').resolve()):
            raise RuntimeError('Mac GUI identity changed')

    def current(self,window):
        self.validate(window)
        items=self.request(window,{'kind':'inspect'})['windows']
        current=next((item for item in items if item.get('hwnd')==window['hwnd']),None)
        keys=('rootx','rooty','width','height','title','visible')
        if current is None or any(current.get(k)!=window.get(k) for k in keys):
            raise RuntimeError('Mac window changed during capture; refresh required')

    def capture(self,window):
        import objc
        import Quartz as Q
        import ScreenCaptureKit as S
        from Foundation import NSMutableData
        with self.lock,objc.autorelease_pool():
            if not Q.CGPreflightScreenCaptureAccess():
                raise PermissionError('Grant Screen Recording to the bundled Python/Terminal in System Settings, then restart projection')
            self.current(window)
            content=completed_call(lambda cb:S.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(True,True,cb))
            selected,crop=choose_window(window,content.windows())
            outer=rect_tuple(selected.frame());width,height=round(outer[2]),round(outer[3])
            filter_=S.SCContentFilter.alloc().initWithDesktopIndependentWindow_(selected)
            config=S.SCStreamConfiguration.alloc().init()
            config.setWidth_(width);config.setHeight_(height)
            config.setShowsCursor_(False);config.setCapturesAudio_(False)
            config.setIgnoreShadowsSingleWindow_(True)
            picture=completed_call(lambda cb:S.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(filter_,config,cb))
            if Q.CGImageGetWidth(picture)!=width or Q.CGImageGetHeight(picture)!=height:
                raise RuntimeError('Unexpected Mac capture scale; frame discarded')
            # sourceRect is ignored for a single-window filter. Crop the image,
            # never the display, after rendering at logical-point dimensions.
            dx,dy,w,h=crop
            picture=Q.CGImageCreateWithImageInRect(picture,Q.CGRectMake(dx,dy,w,h))
            if picture is None or Q.CGImageGetWidth(picture)!=w or Q.CGImageGetHeight(picture)!=h:
                raise RuntimeError('Mac client crop failed')
            output=NSMutableData.data()
            destination=Q.CGImageDestinationCreateWithData(output,'public.png',1,None)
            if destination is None:raise RuntimeError('PNG encoder unavailable')
            Q.CGImageDestinationAddImage(destination,picture,None)
            if not Q.CGImageDestinationFinalize(destination):raise RuntimeError('PNG encoding failed')
            self.current(window)
            latest=completed_call(lambda cb:S.SCShareableContent.getShareableContentExcludingDesktopWindows_onScreenWindowsOnly_completionHandler_(True,True,cb))
            check,check_crop=choose_window(window,latest.windows())
            if check.windowID()!=selected.windowID() or rect_tuple(check.frame())!=outer or check_crop!=crop:
                raise RuntimeError('Mac window identity changed; frame discarded')
            return bytes(output),w,h
