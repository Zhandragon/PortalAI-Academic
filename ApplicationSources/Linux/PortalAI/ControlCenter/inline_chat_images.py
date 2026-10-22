"""Render local output image links without HTTP, remote fetches or tool execution."""
import sys as _instance_sys
from pathlib import Path as _InstancePath
_instance_sys.path.insert(0, str(_InstancePath(__file__).resolve().parents[1]/'Agent'))
from instance_runtime import port as _instance_port, url as _instance_url
import base64
from itertools import islice
from pathlib import PurePosixPath
import re
import subprocess
import threading
import tkinter as tk
from urllib.parse import parse_qs, unquote, urlsplit

IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff'}
_DECODERS = threading.BoundedSemaphore(2)
_MARKDOWN = re.compile(r'!\[([^\]\n]{0,300})\]\((<[^>\n]+>|[^\n]+?)\)(?=\s|$|[.,!])')


def local_reference(url):
    """Only the existing output server's namespace; never trust a URL as a path."""
    if len(url) > 8192:
        return None
    try:
        parsed = urlsplit(url.strip('<>'))
        if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
                or parsed.port != _instance_port('preview') or parsed.username is not None or parsed.password is not None):
            return None
        path = unquote(parsed.path, errors='strict')
        if path == '/media':
            values = parse_qs(parsed.query, max_num_fields=16).get('path', [])
            if len(values) != 1:
                return None
            return values[0] if PurePosixPath(values[0].replace('\\', '/')).suffix.lower() in IMAGE_EXTS else None
        parts = path.lstrip('/').split('/')
        if any(p in ('', '.', '..') or any(c in p for c in ('\\', ':', '\x00')) for p in parts):
            return None
        if PurePosixPath(path).suffix.lower() not in IMAGE_EXTS:
            return None
        return 'Outputs/' + '/'.join(parts)
    except (ValueError, UnicodeError):
        return None


def _image_matches(text):
    # Code examples must remain text. Never interpret incomplete streamed links.
    excluded = [(m.start(), m.end()) for m in re.finditer(r'```[\s\S]*?(?:```|$)|`[^`\n]*`', text)]
    for match in _MARKDOWN.finditer(text):
        if any(start <= match.start() < end for start, end in excluded):
            continue
        reference = local_reference(match[2])
        if reference is not None:
            yield match, reference


def image_links(text):
    for match, reference in _image_matches(text):
        yield match[0], match[1] or 'Image', reference


def thumbnail_bytes(panel, reference):
    """Worker-only, read-only decoding; publication stays on the Tk thread."""
    import media_devices
    from profile_paths import ProfileLocked
    def check():
        panel._check_login()
        if getattr(panel, '_closing', False):
            raise ProfileLocked('Image preview closed')
    check()
    source = panel._resolve_private_reference(reference)
    outputs = panel._resolve_private_reference('Outputs', hydrate=False)
    if not source.is_relative_to(outputs) or source.suffix.lower() not in IMAGE_EXTS:
        raise ValueError('Preview must be an image in this account\'s Outputs')
    if not source.is_file():
        raise FileNotFoundError('The generated image is no longer available')
    if source.stat().st_size > 128 * 1024**2:
        raise ValueError('Image exceeds the inline preview size limit')
    while not _DECODERS.acquire(timeout=.1):
        check()
    proc = None
    try:
        check()
        proc = subprocess.Popen([str(media_devices.ffmpeg_path(panel.root)), '-v', 'error', '-nostdin',
            '-max_alloc', '134217728', '-threads', '1', '-i', str(source), '-frames:v', '1',
            '-filter_threads', '1', '-vf', 'scale=520:520:force_original_aspect_ratio=decrease',
            '-pix_fmt', 'rgba', '-threads', '1', '-f', 'image2pipe', '-c:v', 'png', 'pipe:1'],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        import time
        deadline = time.monotonic() + 20
        while True:
            check()
            if time.monotonic() > deadline:
                raise TimeoutError('Image decoding timed out')
            try:
                data, _ = proc.communicate(timeout=.1)
                break
            except subprocess.TimeoutExpired:
                pass
        check()
        if proc.returncode or not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data) > 2 * 1024**2:
            raise ValueError('The image could not be decoded')
        return data
    finally:
        if proc is not None:
            if proc.poll() is None:
                proc.kill()  # This exact child handle only; never a PID/port lookup.
            proc.communicate()
        _DECODERS.release()


def render_links(panel, start):
    """Replace complete local Markdown images in the assistant's display only."""
    if getattr(panel, '_closing', False):
        return
    text = panel.chat.get(start, 'end-1c')
    matches = list(islice(_image_matches(text), 12))
    if not matches:
        return
    panel._check_login()
    follow = panel._chat_is_near_bottom()
    # Reverse order keeps earlier text offsets stable while replacing links.
    # Tk embedded windows count as indices but not text, so locate by text offset.
    for match, reference in reversed(matches):
        raw, alt = match[0], match[1] or 'Image'
        cursor = start
        index = panel.chat.search(raw, cursor, stopindex='end', exact=True)
        while index and len(panel.chat.get(start, index)) != match.start():
            cursor = f'{index}+1c'
            index = panel.chat.search(raw, cursor, stopindex='end', exact=True)
        if not index:
            continue
        from conversation_cards import ornate_frame
        frame = ornate_frame(panel.chat, panel.COL)
        head = tk.Frame(frame, bg=panel.COL['card'])
        head.pack(fill='x', padx=10, pady=8)
        body = tk.Frame(frame, bg=panel.COL['card'])
        body.pack(fill='both', expand=True)
        frame._portalai_preview_body = body
        frame._portalai_preview_expanded = True
        from elegant_native_ui import ElegantButton
        def toggle(frame=frame, body=body):
            panel._check_login()
            if getattr(panel, '_closing', False):
                return
            expanded = not frame._portalai_preview_expanded
            if expanded:
                body.pack(fill='both', expand=True)
            else:
                body.pack_forget()
            frame._portalai_preview_expanded = expanded
            frame._portalai_preview_toggle.configure(text='Minimize' if expanded else 'Show image')
        button = ElegantButton(head, text='Minimize', command=toggle,
                               bg=panel.COL.get('panel2', panel.COL['card']), fg=panel.COL['text'])
        button.pack(side='right', padx=(8, 0))
        frame._portalai_preview_toggle = button
        caption = tk.Label(head, text=alt, bg=panel.COL['card'], fg=panel.COL['text'], wraplength=300)
        caption._portalai_zoom_wrap_fraction = .60
        caption.pack(side='left', fill='x', expand=True)
        status = tk.Label(body, text='Loading image…', bg=panel.COL['card'], fg=panel.COL['muted'])
        status.pack(padx=12, pady=9)
        panel.chat.configure(state='normal')
        panel.chat.delete(index, f'{index}+{len(raw)}c')
        panel.chat.window_create(index, window=frame)
        panel.chat.configure(state='disabled')
        def worker(frame=frame, status=status, reference=reference):
            try:
                data, error = thumbnail_bytes(panel, reference), None
            except Exception as exc:
                data, error = None, str(exc)
            panel.ev.put(('inline_image_ready', (frame, status, data, error)))
        panel._thread(target=worker, name='PortalAIInlineImage', daemon=True).start()
    if follow:
        panel.chat.see('end')


def finish(panel, event):
    frame, status, data, error = event
    if getattr(panel, '_closing', False) or not frame.winfo_exists():
        return
    panel._check_login()
    if error:
        status.configure(text='Preview unavailable: ' + error[:180], wraplength=420)
        return
    photo = tk.PhotoImage(master=frame, data=base64.b64encode(data), format='png')
    from conversation_cards import preview_label
    label = preview_label(frame._portalai_preview_body, photo, panel.COL)
    label._portalai_image = photo
    status.destroy()
