"""Owned FFplay preview with measured position, seeking and volume controls."""
from pathlib import Path
import json
import math
import os
import queue
import re
import subprocess
import threading
import tkinter as tk
import uuid

from elegant_native_ui import ElegantButton
import media_devices
from profile_paths import capture, ProfileLocked


def time_text(seconds):
    seconds = max(0, int(seconds or 0))
    return (f'{seconds//3600}:{seconds//60%60:02d}:{seconds%60:02d}' if seconds >= 3600
            else f'{seconds//60}:{seconds%60:02d}')


def position_from_stats(line):
    match = re.match(r'^\s*(\d+(?:\.\d+)?)\s+(?:M-A|M-V|A-V):', line)
    return float(match[1]) if match else None


def probe_command(root, path):
    binary = media_devices.ffmpeg_path(root).with_name('ffprobe.exe' if os.name == 'nt' else 'ffprobe')
    return [str(binary), '-v', 'error', '-show_entries', 'format=duration,start_time', '-of', 'json', str(path)]


def player_command(root, path, title, position, volume, start_time=0.):
    target=max(0.,float(position))+float(start_time)
    options = ['-hide_banner', '-loglevel', 'info', '-stats', '-autoexit',
               '-window_title', title, '-volume', str(max(0, min(100, int(volume)))),
               '-ss', f'{max(0., float(position)):.3f}',
               # FFplay -ss alone can display from an earlier keyframe. Drop
               # that preroll without resetting timestamps used by the UI.
               '-vf', f'trim=start={target:.6f}', '-af', f'atrim=start={target:.6f}']
    if os.name == 'nt':
        return [str(Path(root)/'Tools/ffmpeg/bin/ffplay.exe'), *options, str(path)]
    base = media_devices.linux_player_command(root, path)
    base = base[:base.index('-hide_banner')]
    return media_devices.owned_linux_command(root, [*base, *options, str(path)])


class NativeMediaPlayer:
    """A sheet owns its exact process handles and closes them before sealing.

    Seeking/volume changes restart that owned child at the measured timestamp.
    Slider drags commit on release; they never spawn one process per pixel.
    """
    def __init__(self, panel, body, path):
        self.panel, self.app, self.path = panel, panel.app, Path(path)
        self.context = capture(panel.root)
        self.closed = False; self.lock = threading.RLock(); self.proc = None; self.probe = None
        self.reader = None; self.probe_thread = None; self.pending = queue.Queue()
        self.latest_position = None
        self.poll_id = self.seek_id = self.volume_id = None
        self.duration = 0.; self.position = 0.; self.paused = False; self.pause_pending = False
        self.start_time = 0.
        self.hwnd = 0; self.title = ''; self.volume = 70; self.muted = False
        self.dragging = False; self.updating = False; self.autoplay = True; self.launch_muted = False
        c = panel.COL
        self.widget = tk.Frame(body, bg=c['bg']); self.widget.pack(fill='both', expand=True, padx=12, pady=(0,12))
        controls = tk.Frame(self.widget,bg=c['bg']);controls.pack(fill='x',pady=(0,8))
        def button(text, callback):
            item=ElegantButton(controls,text=text,command=callback,bg=c['panel2'],fg=c['text'],bd=0,padx=9,pady=5)
            item.pack(side='left',padx=(0,5));return item
        self.play_button=button('Play',self.toggle);self.stop_button=button('Stop',self.stop)
        self.back=button('−10 s',lambda:self.seek(self.position-10));self.forward=button('+10 s',lambda:self.seek(self.position+10))
        self.screen=tk.Frame(self.widget,bg='#000000',height=120);self.screen.pack(fill='both',expand=True)
        self.screen.bind('<Configure>',self._fit)
        self.status=tk.StringVar(value='Reading media duration…')
        tk.Label(self.widget,textvariable=self.status,bg=c['bg'],fg=c['muted'],anchor='w',wraplength=600).pack(fill='x',pady=(6,2))
        row=tk.Frame(self.widget,bg=c['bg']);row.pack(fill='x')
        self.clock=tk.StringVar(value='0:00 / 0:00')
        tk.Label(row,textvariable=self.clock,bg=c['bg'],fg=c['text'],width=18,anchor='w').pack(side='left')
        self.seek_value=tk.DoubleVar(value=0)
        self.timeline=tk.Scale(row,from_=0,to=1,variable=self.seek_value,resolution=.1,orient='horizontal',showvalue=False,
                               command=self._timeline_key,bg=c['bg'],fg=c['text'],troughcolor=c['panel2'],
                               activebackground=c['gold'],highlightthickness=0,bd=0,state='disabled',takefocus=True)
        self.timeline.pack(side='left',fill='x',expand=True)
        self.timeline.bind('<ButtonPress-1>',self._drag_seek);self.timeline.bind('<B1-Motion>',self._drag_seek)
        self.timeline.bind('<ButtonRelease-1>',self._release_seek)
        volume_row=tk.Frame(self.widget,bg=c['bg']);volume_row.pack(fill='x')
        tk.Label(volume_row,text='Volume',bg=c['bg'],fg=c['text']).pack(side='left')
        self.volume_value=tk.IntVar(value=self.volume)
        self.volume_scale=tk.Scale(volume_row,from_=0,to=100,variable=self.volume_value,resolution=1,orient='horizontal',
            length=160,command=self._volume_changed,bg=c['bg'],fg=c['text'],troughcolor=c['panel2'],activebackground=c['gold'],
            highlightthickness=0,bd=0,takefocus=True)
        self.volume_scale.pack(side='left',padx=10)
        self.volume_drag=False
        self.volume_scale.bind('<ButtonPress-1>',lambda _e:setattr(self,'volume_drag',True),add='+')
        self.volume_scale.bind('<ButtonRelease-1>',self._volume_release,add='+')
        self.mute_value=tk.BooleanVar(value=False)
        tk.Checkbutton(volume_row,text='Mute',variable=self.mute_value,command=self._apply_volume,bg=c['bg'],fg=c['text'],
                       selectcolor=c['panel2'],activebackground=c['bg'],activeforeground=c['text']).pack(side='left')
        self.probe_thread=panel._thread(target=self._probe_duration,name='PortalAIMediaProbe',daemon=True)
        self.probe_thread.start();self.poll_id=self.app.after(80,self._poll)

    def _check(self):
        if self.closed or getattr(self.panel,'_closing',False):raise RuntimeError('Media preview is closed')
        self.panel._check_login()
        if capture(self.panel.root)!=self.context:raise ProfileLocked('Media preview login expired')

    def _probe_duration(self):
        proc=None
        try:
            with self.lock:
                self._check()
                proc=self.probe=subprocess.Popen(probe_command(self.panel.root,self.path),cwd=self.panel.root,
                    env=media_devices.desktop_env(self.panel.root),stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            output,error=proc.communicate(timeout=8)
            if proc.returncode:raise RuntimeError('Media duration is unavailable; use Open externally.')
            info=json.loads(output).get('format') or {}
            value=float(info.get('duration') or 0)
            if not math.isfinite(value) or value<=0:raise RuntimeError('This media has no seekable duration; use Open externally.')
            origin=float(info.get('start_time') or 0)
            if not math.isfinite(origin):raise RuntimeError('This media has invalid timestamps; use Open externally.')
            self.pending.put(('start_time',origin))
            self.pending.put(('duration',value))
        except Exception as exc:self.pending.put(('error',str(exc)))
        finally:
            if proc is not None and proc.poll() is None:self._terminate(proc)
            with self.lock:
                if self.probe is proc:self.probe=None

    @staticmethod
    def _terminate(proc):
        if proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=1.5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=2)

    def _stop_child(self):
        proc=self.proc
        self.hwnd=0
        if proc is not None:self._terminate(proc)
        self.proc=None
        reader=self.reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2)
            if reader.is_alive():raise RuntimeError('Media status reader did not stop safely')
        self.reader=None
        if proc is not None and proc.stderr is not None:proc.stderr.close()

    def _start(self,position,paused=False):
        with self.lock:
            self._check();self._stop_child();self._check()
            self.position=max(0.,min(max(0.,self.duration-.02),float(position)))
            if paused and os.name!='nt':
                # SIGSTOP would defer the Linux parent's death SIGTERM. A
                # paused Linux preview has no live child to orphan on a crash.
                self.paused=True;self.pause_pending=False;self.launch_muted=False
                self.status.set('Paused at selected position.');self.play_button.configure(text='Play');self._display()
                return
            self.paused=bool(paused);self.pause_pending=bool(paused);self.launch_muted=bool(paused)
            self.title='PortalAIPlayer-'+uuid.uuid4().hex
            self.proc=subprocess.Popen(player_command(self.panel.root,self.path,self.title,self.position,
                0 if self.muted or paused else self.volume,self.start_time),cwd=self.panel.root,env=media_devices.desktop_env(self.panel.root),
                stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.reader=self.panel._thread(target=self._read_stats,args=(self.proc,),name='PortalAIMediaStatus',daemon=True)
            try:self.reader.start()
            except Exception:self._terminate(self.proc);self.proc.stderr.close();self.proc=None;raise
        self.status.set('Seeking…' if position else 'Starting playback…');self.play_button.configure(text='Play' if paused else 'Pause')

    def _read_stats(self,proc):
        pending=b'';tail=''
        try:
            while True:
                chunk=proc.stderr.read1(4096)
                if not chunk:break
                pending+=chunk
                rows=re.split(b'[\r\n]',pending);pending=rows.pop()[-8192:]
                for row in rows:
                    line=row.decode('utf-8',errors='replace');value=position_from_stats(line)
                    if value is not None:self.latest_position=(proc,value)
                    elif line.strip():tail=(tail+'\n'+line)[-1200:]
            self.pending.put(('exit',(proc,proc.wait(),tail)))
        except (OSError,ValueError):pass

    def _owned_hwnd(self):
        if os.name!='nt' or self.proc is None or self.proc.poll() is not None:return 0
        import ctypes
        from ctypes import wintypes as w
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.FindWindowW.argtypes=[w.LPCWSTR,w.LPCWSTR];user.FindWindowW.restype=w.HWND
        user.GetWindowThreadProcessId.argtypes=[w.HWND,ctypes.POINTER(w.DWORD)]
        hwnd=self.hwnd or user.FindWindowW(None,self.title);pid=w.DWORD()
        if hwnd:user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        return int(hwnd) if hwnd and pid.value==self.proc.pid else 0

    def _embed(self):
        hwnd=self._owned_hwnd()
        if not hwnd:return
        import ctypes
        from ctypes import wintypes as w
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.SetParent.argtypes=[w.HWND,w.HWND];user.SetParent.restype=w.HWND
        user.GetWindowLongW.argtypes=[w.HWND,ctypes.c_int];user.GetWindowLongW.restype=ctypes.c_long
        user.SetWindowLongW.argtypes=[w.HWND,ctypes.c_int,ctypes.c_long]
        if not self.hwnd:
            style=user.GetWindowLongW(hwnd,-16)
            user.SetParent(hwnd,self.screen.winfo_id())
            user.SetWindowLongW(hwnd,-16,(style|0x40000000|0x10000000)&~(0x80000000|0x00C00000|0x00040000))
            self.hwnd=hwnd;self._fit()

    def _fit(self,_event=None):
        hwnd=self._owned_hwnd()
        if not hwnd:return
        import ctypes
        from ctypes import wintypes as w
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.MoveWindow.argtypes=[w.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,w.BOOL]
        user.MoveWindow(hwnd,0,0,max(1,self.screen.winfo_width()),max(1,self.screen.winfo_height()),True)

    def _set_pause(self,paused):
        if self.proc is None:return False
        if os.name=='nt':
            hwnd=self._owned_hwnd()
            if not hwnd:return False
            import ctypes
            from ctypes import wintypes as w
            user=ctypes.WinDLL('user32',use_last_error=True)
            user.PostMessageW.argtypes=[w.HWND,w.UINT,w.WPARAM,w.LPARAM]
            # SDL uses the native scan code/release bits, not just VK_SPACE.
            user.PostMessageW(hwnd,0x0100,0x20,1|(0x39<<16))
            user.PostMessageW(hwnd,0x0101,0x20,1|(0x39<<16)|(3<<30))
        elif paused:
            # Resume creates a fresh owned player from this measured position.
            self._stop_child()
        self.paused=bool(paused);self.play_button.configure(text='Play' if paused else 'Pause');return True

    def toggle(self):
        if not self.duration:return
        try:
            self._check()
            if self.proc is None or self.proc.poll() is not None or self.launch_muted:
                self._start(0 if self.position>=self.duration-.02 else self.position,False)
            elif self._set_pause(not self.paused):self.status.set('Paused.' if self.paused else 'Playing.')
        except Exception as exc:self.status.set(str(exc))

    def seek(self,value):
        if self.closed or not self.duration:return
        try:
            self._check();target=max(0.,min(self.duration,float(value)))
            if self.proc is None or self.proc.poll() is not None:
                self.position=target;self.status.set('Position selected; press Play.');self._display()
            else:self._start(target,self.paused)
        except Exception as exc:self.status.set(str(exc))

    def _drag_seek(self,event):
        if not self.duration:return 'break'
        self.dragging=True
        if self.seek_id:self.app.after_cancel(self.seek_id);self.seek_id=None
        start=self.timeline.coords(0)[0];end=self.timeline.coords(self.duration)[0]
        value=max(0.,min(1.,(event.x-start)/max(1,end-start)))*self.duration
        self.seek_value.set(value);self.clock.set(time_text(value)+' / '+time_text(self.duration))
        return 'break'

    def _release_seek(self,_event):
        if self.dragging:self.dragging=False;self.seek(self.seek_value.get())
        return 'break'

    def _timeline_key(self,value):
        if self.closed or self.updating or self.dragging:return
        # Tk coalesces Scale commands until idle, after _display's updating
        # guard ends. A programmatic display refresh must never launch a seek.
        if abs(float(value)-round(self.position,1))<.051:return
        if self.seek_id:self.app.after_cancel(self.seek_id)
        self.seek_id=self.app.after(250,lambda:self._commit_key_seek(float(value)))

    def _commit_key_seek(self,value):self.seek_id=None;self.seek(value)

    def _volume_changed(self,_value):
        if self.closed or self.volume_drag:return
        if self.volume_id:self.app.after_cancel(self.volume_id)
        self.volume_id=self.app.after(250,self._apply_volume)

    def _volume_release(self,_event):self.volume_drag=False;self._apply_volume()

    def _apply_volume(self):
        if self.closed:return
        if self.volume_id:self.app.after_cancel(self.volume_id);self.volume_id=None
        value,muted=self.volume_value.get(),self.mute_value.get()
        if (value,muted)==(self.volume,self.muted):return
        self.volume,self.muted=value,muted
        if self.proc is not None and self.proc.poll() is None:
            try:self._start(self.position,self.paused)
            except Exception as exc:self.status.set(str(exc))

    def _display(self):
        if not self.dragging:
            self.updating=True
            try:self.seek_value.set(self.position);self.clock.set(time_text(self.position)+' / '+time_text(self.duration))
            finally:self.updating=False

    def _poll(self):
        self.poll_id=None
        if self.closed:return
        try:self._check()
        except Exception:self.close();return
        latest,self.latest_position=self.latest_position,None
        if latest is not None:self.pending.put(('position',latest))
        try:
            while True:
                kind,value=self.pending.get_nowait()
                if kind=='start_time':self.start_time=value
                elif kind=='duration':
                    self.duration=value;self.timeline.configure(to=value,state='normal');self._display()
                    if self.autoplay:self._start(0)
                elif kind=='error':self.status.set(value)
                elif kind=='position' and value[0] is self.proc:
                    self.position=max(0.,min(self.duration,value[1]-self.start_time));self._display()
                    if self.pause_pending:
                        if self._set_pause(True):self.pause_pending=False;self.status.set('Paused at selected position.')
                    elif not self.paused:self.status.set('Playing.')
                elif kind=='exit' and value[0] is self.proc:
                    self._stop_child()
                    self.status.set('Playback finished.' if value[1]==0 else 'Playback failed: '+value[2][-500:])
                    self.play_button.configure(text='Play')
                    if value[1]==0:self.position=self.duration;self._display()
        except queue.Empty:pass
        except Exception as exc:self.stop();self.status.set(str(exc))
        if os.name=='nt':
            try:self._embed()
            except (OSError,tk.TclError) as exc:self.status.set('Video embedding unavailable: '+str(exc))
        elif self.proc is not None:self.status.set('Paused in the bundled player window.' if self.paused else 'Playing in the bundled player window.')
        self.poll_id=self.app.after(100,self._poll)

    def stop(self):
        self.autoplay=False
        if self.seek_id:self.app.after_cancel(self.seek_id);self.seek_id=None
        if self.volume_id:self.app.after_cancel(self.volume_id);self.volume_id=None
        with self.lock:self._stop_child()
        self.position=0.;self.paused=False;self.pause_pending=False;self._display()
        self.play_button.configure(text='Play');self.status.set('Stopped.')

    def close(self):
        with self.lock:
            self.closed=True;self.autoplay=False
            for name in ('poll_id','seek_id','volume_id'):
                value=getattr(self,name)
                if value:self.app.after_cancel(value);setattr(self,name,None)
            if self.probe is not None:self._terminate(self.probe)
            self._stop_child()
        if self.probe_thread is not None and self.probe_thread is not threading.current_thread():
            self.probe_thread.join(timeout=2)
            if self.probe_thread.is_alive():raise RuntimeError('Media metadata worker did not stop safely')


def attach_player(panel,body,path):
    if os.name=='nt' and not (Path(panel.root)/'Tools/ffmpeg/bin/ffplay.exe').is_file():return False
    panel._native_media_player=NativeMediaPlayer(panel,body,path)
    return True
