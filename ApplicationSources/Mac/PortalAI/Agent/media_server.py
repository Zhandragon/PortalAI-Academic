from __future__ import annotations
from instance_runtime import port as _instance_port, url as _instance_url

import argparse
import io
import json
import mimetypes
import os
import re
import stat
import sys
import secrets
from urllib.parse import parse_qs, urlencode, urlsplit
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_paths import capture, private_path
from media_paths import preview_credentials


class PortableAIOutputHandler(SimpleHTTPRequestHandler):
    """
    Static localhost-only server for PortableAI\\Outputs.

    Paths are resolved and re-checked against the configured Outputs root,
    including symlink resolution, before any file is served.
    """

    server_version = "PortableAI-MediaPreview/15.30"
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map,
                      '.mp4':'video/mp4', '.webm':'video/webm', '.mov':'video/quicktime',
                      '.m4v':'video/mp4', '.wav':'audio/wav', '.mp3':'audio/mpeg',
                      '.flac':'audio/flac', '.m4a':'audio/mp4', '.ogg':'audio/ogg',
                      '.oga':'audio/ogg', '.opus':'audio/ogg'}

    def __init__(self, *args, directory=None, portable_root=None, profile_context=None, capability=None, **kwargs):
        self._root = Path(directory or os.getcwd()).resolve()
        self._portable_root = Path(portable_root or Path(__file__).resolve().parents[1]).resolve()
        self._profile_context = profile_context
        self._capability = capability
        super().__init__(*args, directory=str(self._root), **kwargs)

    def _authorized(self):
        try:
            current = capture(self._portable_root)
            if current != self._profile_context:
                return False
            if current is None:
                return True
            supplied = parse_qs(urlsplit(self.path).query, max_num_fields=16).get('portal_token', [])
            if len(supplied) != 1 or not self._capability or not secrets.compare_digest(supplied[0], self._capability):
                return False
            return self._root == private_path(self._portable_root, 'Outputs', context=current)
        except (OSError, ValueError, PermissionError):
            return False

    def translate_path(self, path: str) -> str:
        candidate = Path(super().translate_path(path)).resolve()
        try:
            candidate.relative_to(self._root)
        except ValueError:
            # Return a guaranteed-nonexistent in-root path rather than expose
            # anything outside PortableAI\Outputs through traversal/symlinks.
            return str(self._root / "__portableai_blocked__")
        return str(candidate)

    def log_message(self, fmt: str, *args) -> None:
        # Deliberately quiet: image previews should not create console/log spam.
        return

    def end_headers(self) -> None:
        # OpenGUI/Electron may load the image from a different localhost origin.
        if self._profile_context is None:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cross-Origin-Resource-Policy", "cross-origin")
        self.send_header("Cache-Control", "no-store" if self._profile_context else "no-cache")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def do_GET(self) -> None:
        if not self._authorized():
            self.send_error(403, 'Preview session is locked or expired')
            return
        if self.path.split("?", 1)[0] == "/__health__":
            payload = json.dumps(
                {
                    "ok": True,
                    "service": "PortableAI Media Preview",
                    "root": str(self._root),
                    "pid": os.getpid(),
                    "byte_ranges": True,
                    "media_player": True,
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        super().do_GET()

    def do_HEAD(self):
        if not self._authorized():
            self.send_error(403, 'Preview session is locked or expired')
            return
        super().do_HEAD()

    def send_head(self):
        self._response_range = None
        # SimpleHTTPRequestHandler does not use the application path resolver.
        # Restore only this authorized file, never the complete Outputs tree.
        if not self._authorized():
            self.send_error(403, 'Preview session is locked or expired')
            return None
        if self._profile_context is not None:
            try:
                candidate = Path(self.translate_path(self.path))
                relative = candidate.relative_to(self._root)
                if relative.parts and relative.name != '__portableai_blocked__':
                    from profile_hydration import materialize
                    materialize(self._portable_root, 'Outputs/' + relative.as_posix(), recursive=False)
                if not self._authorized():
                    raise PermissionError('Preview session ended during file restoration')
            except PermissionError:
                self.send_error(403, 'Preview session is locked or expired')
                return None
            except (OSError, ValueError, RuntimeError):
                self.send_error(503, 'Requested media could not be restored safely')
                return None
        candidate = Path(self.translate_path(self.path))
        if candidate.is_dir():
            return super().send_head()
        try:
            query = parse_qs(urlsplit(self.path).query, max_num_fields=16)
        except ValueError:
            self.send_error(400, 'Invalid preview query')
            return None
        if query.get('portal_player') == ['1'] and candidate.is_file():
            content_type = self.guess_type(str(candidate))
            kind = content_type.split('/', 1)[0]
            if kind in ('audio', 'video'):
                from media_player import player_document
                source_url = urlsplit(self.path).path
                if self._profile_context is not None:
                    source_url += '?' + urlencode({'portal_token':self._capability})
                try:
                    payload, csp = player_document(source_url, candidate.name, kind)
                except ValueError:
                    self.send_error(400, 'Invalid preview path')
                    return None
                if not self._authorized():
                    self.send_error(403, 'Preview session is locked or expired')
                    return None
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('Content-Security-Policy', csp)
                self.end_headers()
                return io.BytesIO(payload)
        try:
            source = candidate.open('rb')
        except OSError:
            self.send_error(404, 'Requested media was not found')
            return None
        try:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode):
                self.send_error(404, 'Requested media was not found')
                source.close()
                return None
            if not self._authorized():
                self.send_error(403, 'Preview session is locked or expired')
                source.close()
                return None
            size = info.st_size
            etag = '"%x-%x-%x"' % (info.st_ino, info.st_size, info.st_mtime_ns)
            requested = self.headers.get('Range') if self.command == 'GET' else None
            # A stale If-Range must receive the whole current representation.
            if_range = self.headers.get('If-Range')
            if if_range and if_range not in (etag, self.date_time_string(info.st_mtime)):
                requested = None
            try:
                selected = byte_range(requested, size)
            except ValueError:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.send_header('Accept-Ranges', 'bytes')
                self.end_headers()
                source.close()
                return None
            start, length = selected if selected is not None else (0, size)
            self.send_response(206 if selected is not None else 200)
            self.send_header('Content-Type', self.guess_type(str(candidate)))
            self.send_header('Content-Length', str(length))
            self.send_header('Accept-Ranges', 'bytes')
            self.send_header('Last-Modified', self.date_time_string(info.st_mtime))
            self.send_header('ETag', etag)
            if selected is not None:
                self.send_header('Content-Range', f'bytes {start}-{start+length-1}/{size}')
            self.end_headers()
            self._response_range = (start, length)
            return source
        except BaseException:
            source.close()
            raise

    def copyfile(self, source, outputfile):
        selected = getattr(self, '_response_range', None)
        if selected is None:
            return super().copyfile(source, outputfile)
        start, remaining = selected
        source.seek(start)
        # Bounded chunks avoid loading whole videos into RAM; a logout also
        # revokes a transfer already in progress, not just subsequent requests.
        try:
            while remaining and self._authorized():
                chunk = source.read(min(65536, remaining))
                if not chunk or not self._authorized():
                    break
                outputfile.write(chunk)
                remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # Browser scrubbing routinely cancels the previous range.

    def list_directory(self, path):
        if self._profile_context is not None:
            self.send_error(403, 'Directory listing is disabled')
            return None
        return super().list_directory(path)


def byte_range(header, size):
    """Return (offset, length) for a single GET byte range, or full response.

    Browsers seek using single ranges. Unknown units and multipart requests
    are ignored (a permitted full 200 response), never partially mis-served.
    """
    if not header or not header.startswith('bytes=') or ',' in header:
        return None
    match = re.fullmatch(r'bytes=(\d{0,20})-(\d{0,20})', header.strip())
    if not match or not any(match.groups()) or size <= 0:
        raise ValueError('Invalid or unsatisfiable byte range')
    first, last = match.groups()
    if not first:
        count = int(last)
        if count <= 0:
            raise ValueError('Empty suffix byte range')
        start = max(0, size-count)
        return start, size-start
    start = int(first)
    end = min(size-1, int(last)) if last else size-1
    if start >= size or end < start:
        raise ValueError('Unsatisfiable byte range')
    return start, end-start+1


def main() -> int:
    parser = argparse.ArgumentParser(description="PortableAI localhost media preview server")
    parser.add_argument("--root", required=True, help="PortableAI Outputs directory")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=_instance_port('preview'))
    parser.add_argument("--pid-file", default=None)
    args = parser.parse_args()

    if args.host not in ('127.0.0.1', '::1', 'localhost'):
        parser.error('Media preview must bind to loopback')
    portable_root = Path(__file__).resolve().parents[1]
    context = capture(portable_root)

    root = Path(args.root).expanduser().resolve()
    if context is not None and root != private_path(portable_root, 'Outputs', context=context):
        parser.error('Media preview must serve only the active profile Outputs')
    root.mkdir(parents=True, exist_ok=True)

    # Register a few common media types explicitly for Windows installs whose
    # registry/MIME database may be incomplete.
    mimetypes.add_type("image/png", ".png")
    mimetypes.add_type("image/jpeg", ".jpg")
    mimetypes.add_type("image/jpeg", ".jpeg")
    mimetypes.add_type("image/webp", ".webp")
    mimetypes.add_type("image/gif", ".gif")
    mimetypes.add_type("video/mp4", ".mp4")
    mimetypes.add_type("video/webm", ".webm")
    mimetypes.add_type("audio/wav", ".wav")
    mimetypes.add_type("audio/mpeg", ".mp3")
    mimetypes.add_type("audio/mp4", ".m4a")
    mimetypes.add_type("audio/flac", ".flac")

    handler = partial(PortableAIOutputHandler, directory=str(root), portable_root=portable_root,
                      profile_context=context, capability=preview_credentials(portable_root))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.daemon_threads = True

    if args.pid_file:
        pid_path = Path(args.pid_file).expanduser().resolve()
        pid_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            pid_path.write_text(str(os.getpid()), encoding="ascii")
        except Exception:
            pass
    else:
        pid_path = None

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()
        if pid_path:
            try:
                if pid_path.exists() and pid_path.read_text(encoding="ascii").strip() == str(os.getpid()):
                    pid_path.unlink()
            except Exception:
                pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
