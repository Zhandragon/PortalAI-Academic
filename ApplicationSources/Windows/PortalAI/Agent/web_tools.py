from __future__ import annotations
from instance_runtime import port as _instance_port, url as _instance_url

import argparse
import gzip
import html
import io
import ipaddress
import json
import os
import queue
from pathlib import Path
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
import uuid
from contextvars import ContextVar, copy_context
from contextlib import contextmanager
from functools import wraps
from html.parser import HTMLParser
from typing import Any

sys.path.insert(0,str(Path(__file__).resolve().parent))
from web_state import WebState
from profile_paths import private_path, capture, ProfileLocked, _contained
from media_paths import media_output, preview_url as authenticated_preview_url, owned_preview
from runtime_policy import require_space
from web_tls import default_context, certificate_error

ROOT = Path(__file__).resolve().parents[1]


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0 Safari/537.36 PortableAI/15.15"
)
DEFAULT_TIMEOUT = 12
DEFAULT_SEARCH_RESULTS = 6
MAX_DOWNLOAD_BYTES = 3_000_000
MAX_FETCH_CHARS = 12_000


class WebAccessError(RuntimeError):
    def __init__(self,message,**details):
        super().__init__(message)
        self.details={'message':message,**details}


class WebLookupLimit(WebAccessError):
    def __init__(self):
        super().__init__('The bounded web operation finished. Use the returned evidence or try a different source.',
                         category='web_lookup_limit', retry_recommended=False)


class ImageLookupLimit(WebLookupLimit):
    def __init__(self):
        WebAccessError.__init__(self, 'The bounded image lookup finished. Use the returned candidates or refine the query; an exact match has not been verified.',
                                category='image_lookup_limit', retry_recommended=False)


class WebRequestBudget:
    """One operation, including nested provider/page requests and redirects."""
    limit_error = WebLookupLimit

    def __init__(self, seconds=45, requests=12):
        self.deadline = time.monotonic()+seconds
        self.limit = requests
        self.requests = 0
        self.reserved_seconds = 0
        self.reserved_requests = 0

    def remaining(self):
        return self.deadline - self.reserved_seconds - time.monotonic()

    def check(self):
        if self.remaining() <= 0: raise self.limit_error()

    def request_timeout(self, requested):
        self.check()
        if self.requests >= self.limit - self.reserved_requests: raise self.limit_error()
        self.requests += 1
        return min(float(requested), max(.01, self.remaining()))

    @contextmanager
    def reserve(self, seconds, requests):
        previous = self.reserved_seconds, self.reserved_requests
        self.reserved_seconds += seconds
        self.reserved_requests += requests
        try: yield
        finally: self.reserved_seconds, self.reserved_requests = previous


class ImageRequestBudget(WebRequestBudget):
    limit_error = ImageLookupLimit


_IMAGE_BUDGET = ContextVar('portalai_image_request_budget', default=None)
_REQUEST_SCOPE = ContextVar('portalai_web_request_scope', default=None)


def _image_operation(function):
    @wraps(function)
    def bounded(*args, **kwargs):
        if _IMAGE_BUDGET.get() is not None: return function(*args, **kwargs)
        token = _IMAGE_BUDGET.set(ImageRequestBudget())
        try: return function(*args, **kwargs)
        finally: _IMAGE_BUDGET.reset(token)
    return bounded


def _web_operation(function):
    @wraps(function)
    def bounded(*args, **kwargs):
        if _IMAGE_BUDGET.get() is not None: return function(*args, **kwargs)
        token = _IMAGE_BUDGET.set(WebRequestBudget())
        try: return function(*args, **kwargs)
        finally: _IMAGE_BUDGET.reset(token)
    return bounded


def _check_request():
    budget = _IMAGE_BUDGET.get()
    if budget is not None: budget.check()
    scope = _REQUEST_SCOPE.get()
    if scope and (scope[1].is_set() or time.monotonic() >= scope[0]):
        raise WebAccessError('The network request exceeded its elapsed-time allowance; no response was accepted.',
                             category='request_timeout', retry_after_seconds=30)


def _web_error(exc):
    if isinstance(exc,WebAccessError):return dict(exc.details)
    certificate = certificate_error(exc)
    if certificate is not None:return certificate
    if isinstance(exc,urllib.error.HTTPError):
        code=exc.code
        category='access_denied' if code in (401,403) else 'rate_limited' if code==429 else 'http_error'
        messages={401:'Authentication is required by this provider.',
                  403:'The server refused automated access. This is a provider/site restriction, not proof that search has no results.',
                  429:'The server rate-limited this request. Wait for the cooldown before trying again.'}
        delay=900 if code in (401,403) else 60
        retry=(exc.headers or {}).get('Retry-After')
        if retry:
            try:delay=int(retry)
            except ValueError:
                try:
                    from email.utils import parsedate_to_datetime
                    delay=int(parsedate_to_datetime(retry).timestamp()-time.time())
                except (ValueError,TypeError,OverflowError):pass
        return {'category':category,'http_status':code,'retry_after_seconds':max(1,min(86400,delay)),
                'message':messages.get(code,f'The server returned HTTP {code}.')}
    return {'category':'connection_or_parse_error','message':type(exc).__name__+': '+str(exc)[:240],
            'retry_after_seconds':30}


def _check_challenge(text):
    prefix=text[:30000].lower()
    if any(token in prefix for token in ('id="challenge-form"','id="anomaly-form"','class="anomaly-modal',
                                         '<title>just a moment...</title>','<title>attention required! | cloudflare</title>',
                                         '<title>captcha</title>', 'id="b_captcha"', 'id="b_captcha_container"')):
        raise WebAccessError('The site returned a browser/bot challenge; no page content was fetched.',
                             category='browser_challenge',http_status=403,retry_after_seconds=900)


def emit(payload: dict[str, Any], code: int = 0) -> None:
    # OpenGUI's Windows shell can expose a legacy cp1252 stdout encoding.
    # ASCII-safe JSON prevents arbitrary webpage Unicode from crashing print().
    text = json.dumps(payload, ensure_ascii=True, indent=2)
    try:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
    except UnicodeEncodeError:
        # Defensive fallback for unusual redirected consoles.
        data = (text + "\n").encode("utf-8", errors="backslashreplace")
        if hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
        else:
            raise
    raise SystemExit(code)


def _blocked_ip(ip_text: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_text)
    except ValueError:
        return True
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _candidate_url(url: str) -> urllib.parse.ParseResult:
    """Validate inert result metadata without doing DNS for every candidate.

    Destination DNS is still validated before every real request/redirect.
    Merely reporting a provider's URL must not spend the lookup on dozens of
    DNS lookups or treat a temporary resolver failure as 'no images found'.
    """
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 32 for c in url):
        raise ValueError('Invalid public URL.')
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http:// and https:// URLs are allowed.")
    if not parsed.hostname:
        raise ValueError("URL has no hostname.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError('Credentials embedded in URLs are not supported.')

    host = parsed.hostname.strip().lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ValueError("Local/private hosts are not allowed.")

    try: address = ipaddress.ip_address(host)
    except ValueError: address = None
    if address is not None and _blocked_ip(str(address)):
        raise ValueError('Private/non-public addresses are not allowed.')
    # Also validate malformed ports before any network work.
    parsed.port
    return parsed


def _validate_public_url(url: str) -> urllib.parse.ParseResult:
    parsed = _candidate_url(url)
    host = parsed.hostname.strip().lower()
    _check_request()

    try:
        addresses = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host {host!r}: {exc}") from exc
    _check_request()

    resolved: set[str] = set()
    for info in addresses:
        addr = info[4][0]
        resolved.add(addr)
        if _blocked_ip(addr):
            raise ValueError(f"Refusing private/non-public destination: {host} -> {addr}")

    if not resolved:
        raise ValueError(f"No IP addresses resolved for {host!r}.")
    return parsed


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _check_request()
        budget = _IMAGE_BUDGET.get()
        if budget is not None: budget.request_timeout(DEFAULT_TIMEOUT)
        absolute = urllib.parse.urljoin(req.full_url, newurl)
        _validate_public_url(absolute)
        if req.has_header('X-subscription-token') and (urllib.parse.urlparse(absolute).scheme != 'https' or
                urllib.parse.urlparse(absolute).netloc != urllib.parse.urlparse(req.full_url).netloc):
            raise ValueError('Refusing to forward a search API credential outside its HTTPS origin')
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(SafeRedirectHandler(),
                                      urllib.request.HTTPSHandler(context=default_context()))


def _request_bytes(
    url: str,
    *,
    timeout: int = DEFAULT_TIMEOUT,
    headers: dict[str, str] | None = None,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
) -> tuple[bytes, str, str]:
    """Bound the complete network request, including blocking system DNS.

    Only pure network/byte decoding runs in the daemon. It cannot write cache,
    user files or profile state. A timed-out resolver may finish later, but the
    cancellation check prevents a subsequent HTTP request or accepted result;
    it cannot delay CLI exit. TLS and redirect destination checks stay enabled.
    """
    budget = _IMAGE_BUDGET.get()
    if budget is not None: timeout = budget.request_timeout(timeout)
    cancelled = threading.Event()
    token = _REQUEST_SCOPE.set((time.monotonic() + timeout, cancelled))
    context = copy_context()
    _REQUEST_SCOPE.reset(token)
    results = queue.Queue(maxsize=1)
    def worker():
        try: result = (True, _request_bytes_sync(url, timeout=timeout, headers=headers, max_bytes=max_bytes))
        except BaseException as exc: result = (False, exc)
        results.put_nowait(result)
    threading.Thread(target=lambda: context.run(worker), name='PortalAI-web-request', daemon=True).start()
    try:
        ok, result = results.get(timeout=timeout)
    except queue.Empty:
        cancelled.set()
        if budget is not None: budget.check()
        raise WebAccessError('The network request timed out, including DNS/redirect/response time. Try another source.',
                             category='request_timeout', retry_after_seconds=30) from None
    finally:
        # Also cancel a resolver/redirect if the calling thread is interrupted.
        cancelled.set()
    if budget is not None: budget.check()
    if not ok: raise result
    return result


def _request_bytes_sync(url, *, timeout, headers, max_bytes):
    budget = _IMAGE_BUDGET.get()
    _check_request()
    _validate_public_url(url)
    _check_request()
    req_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    if headers:
        req_headers.update(headers)

    req = urllib.request.Request(url, headers=req_headers)
    with _opener().open(req, timeout=timeout) as resp:
        _check_request()
        final_url = resp.geturl()
        _validate_public_url(final_url)
        content_type = (resp.headers.get("Content-Type") or "").lower()
        chunks = []; received = 0
        while received <= max_bytes:
            _check_request()
            # read1 avoids waiting to fill a buffer with dribbled data. The
            # caller also imposes a total wall-clock limit on this worker.
            block = resp.read1(min(65536, max_bytes+1-received))
            if not block: break
            chunks.append(block); received += len(block)
        _check_request()
        data = b''.join(chunks)
        if len(data) > max_bytes:
            raise ValueError(f"Response exceeded {max_bytes:,} bytes.")
        encoding=(resp.headers.get('Content-Encoding') or '').strip().lower()
        if encoding in ('gzip','x-gzip') or (not encoding and data.startswith(b'\x1f\x8b') and ('text/' in content_type or 'json' in content_type)):
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                data=compressed.read(max_bytes+1)
        elif encoding=='deflate':
            decoder=zlib.decompressobj()
            data=decoder.decompress(data,max_bytes+1)
            if len(data)<=max_bytes and not decoder.eof:
                raise ValueError('Truncated or oversized compressed response')
        elif encoding not in ('','identity'):
            raise ValueError('Unsupported HTTP content encoding: '+encoding)
        if len(data)>max_bytes:
            raise ValueError(f'Decompressed response exceeded {max_bytes:,} bytes.')
        _check_request()
        return data, final_url, content_type


def _decode(data: bytes, content_type: str) -> str:
    charset = "utf-8"
    m = re.search(r"charset\s*=\s*['\"]?([a-zA-Z0-9._-]+)", content_type)
    if m:
        charset = m.group(1)
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def _ddg_real_url(href: str) -> str:
    href = html.unescape(href)
    if href.startswith("//"):
        href = "https:" + href
    absolute = urllib.parse.urljoin("https://html.duckduckgo.com/", href)
    parsed = urllib.parse.urlparse(absolute)
    qs = urllib.parse.parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return urllib.parse.unquote(qs["uddg"][0])
    return absolute


class DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture_title = False
        self._capture_snippet = False
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []

    @staticmethod
    def _classes(attrs) -> set[str]:
        for key, value in attrs:
            if key == "class" and value:
                return set(value.split())
        return set()

    def handle_starttag(self, tag, attrs):
        classes = self._classes(attrs)
        attr = dict(attrs)

        if tag == "a" and (
            "result__a" in classes
            or "result-link" in classes
        ):
            href = attr.get("href", "")
            if not href:
                return
            # Finish any prior result that never received a snippet.
            self._finish_if_needed()
            self._current = {"title": "", "url": _ddg_real_url(href), "snippet": ""}
            self._capture_title = True
            self._title_parts = []

        if self._current and tag in {"a", "div", "span", "td"} and (
            "result__snippet" in classes
            or "result-snippet" in classes
        ):
            self._capture_snippet = True
            self._snippet_parts = []

    def handle_endtag(self, tag):
        if self._capture_title and tag == "a":
            self._capture_title = False
            if self._current is not None:
                self._current["title"] = " ".join(" ".join(self._title_parts).split())

        if self._capture_snippet and tag in {"a", "div", "span", "td"}:
            self._capture_snippet = False
            if self._current is not None:
                self._current["snippet"] = " ".join(" ".join(self._snippet_parts).split())
                self._finish_if_needed(force=True)

    def handle_data(self, data):
        if self._capture_title:
            self._title_parts.append(data)
        if self._capture_snippet:
            self._snippet_parts.append(data)

    def _finish_if_needed(self, force: bool = False):
        if not self._current:
            return
        if force or self._current.get("title"):
            url = self._current.get("url", "")
            if url.startswith(("http://", "https://")):
                self.results.append(self._current)
            self._current = None


def search_duckduckgo(query: str, limit: int, *, lite: bool = False) -> list[dict[str, str]]:
    params = urllib.parse.urlencode({"q": query})
    base='https://lite.duckduckgo.com/lite/' if lite else 'https://html.duckduckgo.com/html/'
    url = f"{base}?{params}"
    data, _, content_type = _request_bytes(
        url,
        headers={"Referer": "https://duckduckgo.com/"},
    )
    text = _decode(data, content_type)
    _check_challenge(text)
    parser = DuckDuckGoParser()
    parser.feed(text)
    parser._finish_if_needed(force=True)

    clean: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in parser.results:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        try:
            _candidate_url(url)
        except Exception:
            continue
        seen.add(url)
        clean.append(
            {
                "title": item.get("title", "").strip(),
                "url": url,
                "snippet": item.get("snippet", "").strip(),
            }
        )
        if len(clean) >= limit:
            break
    return clean


def search_bing(query: str, limit: int) -> list[dict[str, str]]:
    from web_search_fallback import BingSearchParser
    url = 'https://www.bing.com/search?' + urllib.parse.urlencode({'q': query})
    data, _, content_type = _request_bytes(url)
    text = _decode(data, content_type)
    _check_challenge(text)
    parser = BingSearchParser(_candidate_url, limit)
    parser.feed(text)
    parser.finish()
    if not parser.results:
        raise WebAccessError('The search page returned no parseable organic results.',
                             category='no_parseable_results', retry_after_seconds=60)
    return parser.results


def search_brave(query: str, limit: int, api_key: str) -> list[dict[str, str]]:
    params = urllib.parse.urlencode({"q": query, "count": max(1, min(limit, 20))})
    url = f"https://api.search.brave.com/res/v1/web/search?{params}"
    data, _, content_type = _request_bytes(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
    )
    payload = json.loads(_decode(data, content_type))
    results = []
    for item in payload.get("web", {}).get("results", []):
        target = item.get("url", "")
        if not target:
            continue
        try:
            _candidate_url(target)
        except Exception:
            continue
        results.append(
            {
                "title": re.sub(r"<[^>]+>", "", item.get("title", "")).strip(),
                "url": target,
                "snippet": re.sub(r"<[^>]+>", "", item.get("description", "")).strip(),
            }
        )
        if len(results) >= limit:
            break
    return results


@_web_operation
def web_search(query: str, limit: int = DEFAULT_SEARCH_RESULTS, *, fresh: bool = False) -> dict[str, Any]:
    query = " ".join(query.split())
    if not query:
        raise ValueError("Search query is empty.")
    limit = max(1, min(int(limit), 12))

    brave_key = os.environ.get("BRAVE_SEARCH_API_KEY", "").strip()
    errors=[];warnings=[];state=WebState()
    try:
        cached=None if fresh else state.cached(query,limit)
        if cached:return {'query':query,**cached,'provider_errors':[]}
    except ProfileLocked:raise
    except Exception:warnings.append('Portable search cache unavailable; continuing without cached results.')
    providers=([('brave',lambda:search_brave(query,limit,brave_key))] if brave_key else [])+[
        ('duckduckgo',lambda:search_duckduckgo(query,limit)),
        ('bing',lambda:search_bing(query,limit)),
        ('duckduckgo-lite',lambda:search_duckduckgo(query,limit,lite=True))]
    for name,search in providers:
        state.check()
        try:cooldown=state.cooling(name)
        except ProfileLocked:raise
        except Exception:cooldown=None
        if cooldown:errors.append(cooldown);continue
        try:
            results=search()
            state.check()
            if not results:
                errors.append({'provider':name,'category':'no_parseable_results','message':'No parseable results returned.'})
                continue
            result={'provider':name,'query':query,'results':results,'cached':False,'provider_errors':errors}
            try:state.save(query,limit,result)
            except ProfileLocked:raise
            except Exception:warnings.append('Could not save the portable search cache.')
            if warnings:result['warnings']=warnings
            state.check()
            return result
        except (ProfileLocked, WebLookupLimit):raise
        except Exception as exc:
            detail={'provider':name,**_web_error(exc)};errors.append(detail)
            try:state.block(name,detail.get('retry_after_seconds',30),detail['message'])
            except ProfileLocked:raise
            except Exception:pass
    raise WebAccessError('Search is unavailable: '+ ' | '.join(e['provider']+': '+e['message'] for e in errors)+
                         ' The optional BRAVE_SEARCH_API_KEY enables the existing independent API route. No blocked page was bypassed.',
                         category='search_unavailable',provider_errors=errors)


class PageTextParser(HTMLParser):
    BLOCK_TAGS = {
        "p", "div", "section", "article", "main", "header", "footer", "li",
        "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "blockquote",
    }
    SKIP_TAGS = {"script", "style", "noscript", "svg", "canvas", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.title_depth = 0
        self.title_parts: list[str] = []
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag == "title":
            self.title_depth += 1
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self.skip_depth:
            self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "title" and self.title_depth:
            self.title_depth -= 1
        if tag in self.BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        if self.title_depth:
            self.title_parts.append(data)
        self.parts.append(data)


def _clean_text(text: str) -> str:
    lines = []
    for line in text.replace("\r", "\n").split("\n"):
        line = " ".join(line.split())
        if line:
            lines.append(line)
    return "\n".join(lines)



class PageImageParser(HTMLParser):
    """Extract high-value image metadata from a public HTML page."""

    def __init__(self, page_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.page_url = page_url
        self.candidates: list[dict[str, str]] = []

    def _add(self, url: str, source: str, alt: str = "") -> None:
        if not url or len(self.candidates) >= 256:
            return
        url = html.unescape(url.strip())
        if url.startswith("data:"):
            return
        absolute = urllib.parse.urljoin(self.page_url, url)
        if not absolute.startswith(("http://", "https://")):
            return
        self.candidates.append(
            {
                "image_url": absolute,
                "source": source,
                "alt": " ".join(alt.split())[:300],
            }
        )

    def _srcset(self, value, source, alt=''):
        # Keep responsive/lazy images available without returning raw HTML.
        # Data URIs and invalid entries are rejected by _add/_candidate_url.
        # Commas inside a data URI are not candidate separators. Decline that
        # attribute instead of inventing a relative URL from base64 payload.
        if 'data:' in value.lower(): return
        entries = []
        for item in value.split(',')[:32]:
            parts = item.strip().split()
            if not parts: continue
            size = 0
            if len(parts) > 1:
                try: size = float(parts[-1].rstrip('wx'))
                except ValueError: pass
            entries.append((size, parts[0]))
        for _size, url in sorted(entries, reverse=True):
            self._add(url, source, alt)

    def handle_starttag(self, tag, attrs):
        attr = {str(k).lower(): (v or "") for k, v in attrs}
        tag = tag.lower()

        if tag == "meta":
            key = (attr.get("property") or attr.get("name") or attr.get("itemprop") or '').lower()
            content = attr.get("content", "")
            if key in {
                "og:image",
                "og:image:url",
                "og:image:secure_url",
                "twitter:image",
                "twitter:image:src",
                "image",
            }:
                self._add(content, key)

        elif tag == "link":
            rel = attr.get("rel", "").lower()
            if "image_src" in rel or "preload" in rel and attr.get("as", "").lower() == "image":
                self._add(attr.get("href", ""), f"link:{rel}")

        elif tag == "img":
            alt = attr.get("alt", "")
            self._srcset(attr.get('data-srcset') or attr.get('srcset', ''), 'img:srcset', alt)
            for key in ('data-src', 'data-original', 'data-lazy-src', 'src'):
                self._add(attr.get(key, ''), 'img:' + key, alt)
        elif tag == 'source':
            self._srcset(attr.get('srcset', ''), 'source:srcset')


def _page_image_candidates(page_url: str, max_candidates: int = 8) -> list[dict[str, str]]:
    data, final_url, content_type = _request_bytes(page_url, max_bytes=2_000_000)
    try:
        _image_bytes_extension(data)
    except ValueError:
        if content_type.startswith('image/'):raise
    else:
        return [{'image_url': final_url, 'source': 'direct-image', 'alt': ''}]
    text = _decode(data, content_type)
    _check_challenge(text)
    if "html" not in content_type.lower() and "<html" not in text[:1200].lower():
        return []

    return _html_image_candidates(text, final_url, max_candidates)


def _html_image_candidates(text, final_url, max_candidates=8):
    """Extract inert candidate metadata; actual downloads validate DNS/bytes."""
    parser = PageImageParser(final_url)
    parser.feed(text)

    # Prefer social/metadata images over arbitrary page chrome.
    priority = {
        "og:image": 0,
        "og:image:url": 0,
        "og:image:secure_url": 0,
        "twitter:image": 1,
        "twitter:image:src": 1,
        "image": 2,
    }
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in sorted(parser.candidates, key=lambda x: priority.get(x["source"], 10)):
        u = item["image_url"]
        if u in seen:
            continue
        try:
            _candidate_url(u)
        except ValueError:
            continue
        seen.add(u)
        out.append(item)
        if len(out) >= max_candidates:
            break
    return out



def _json_request(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    max_bytes: int = 3_000_000,
) -> dict[str, Any]:
    data, _, content_type = _request_bytes(
        url,
        headers=headers,
        max_bytes=max_bytes,
    )
    text = _decode(data, content_type)
    _check_challenge(text)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError('Image provider returned an unexpected JSON response')
    if payload.get('challenge') or 'challenge' in str(payload.get('response_type', '')).lower():
        raise WebAccessError('The image provider returned a browser/bot challenge, not image results.',
                             category='browser_challenge',http_status=403,retry_after_seconds=900)
    if payload.get('error'):
        error = payload['error']
        message = error.get('info', error.get('code', 'Unknown API error')) if isinstance(error, dict) else str(error)
        raise WebAccessError('Image API error: ' + str(message)[:240], category='provider_error',retry_after_seconds=60)
    return payload


def _wikipedia_lead_images(query: str, limit: int = 3) -> list[dict[str, str]]:
    """
    Find lead/original images for the most relevant English Wikipedia pages.

    This is particularly useful for named people/places/entities because it
    gives a real existing image rather than a generic page-card image.
    """
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "0",
        "gsrlimit": str(max(1, min(limit, 5))),
        "prop": "pageimages|info",
        "piprop": "thumbnail|original|name",
        "pithumbsize": "1600",
        "inprop": "url",
        "redirects": "1",
    }
    url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params)
    payload = _json_request(url)

    pages = payload.get("query", {}).get("pages", {})
    ordered = sorted(
        pages.values(),
        key=lambda p: int(p.get("index", 999999)),
    )

    out: list[dict[str, str]] = []
    for page in ordered:
        image = (
            page.get("original", {}).get("source")
            or page.get("thumbnail", {}).get("source")
        )
        if not image:
            continue
        try:
            _candidate_url(image)
        except (ProfileLocked, WebLookupLimit):raise
        except Exception:
            continue

        out.append(
            {
                "title": page.get("title", ""),
                "page_url": page.get("fullurl", ""),
                "image_url": image,
                "image_source": "wikipedia-lead",
                "alt": page.get("pageimage", ""),
            }
        )
    return out


def _wikimedia_commons_images(query: str, limit: int = 8) -> list[dict[str, str]]:
    """
    Search Wikimedia Commons' file namespace and return direct image URLs.

    Uses documented MediaWiki generator=search + prop=imageinfo.
    """
    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": str(max(1, min(limit, 20))),
        "prop": "imageinfo|info",
        "iiprop": "url|mime",
        "iiurlwidth": "1600",
        "inprop": "url",
    }
    url = "https://commons.wikimedia.org/w/api.php?" + urllib.parse.urlencode(params)
    payload = _json_request(url)

    pages = payload.get("query", {}).get("pages", {})
    ordered = sorted(
        pages.values(),
        key=lambda p: int(p.get("index", 999999)),
    )

    out: list[dict[str, str]] = []
    for page in ordered:
        info = (page.get("imageinfo") or [{}])[0]
        mime = (info.get("mime") or "").lower()
        if mime and not mime.startswith("image/"):
            continue

        image = info.get("thumburl") or info.get("url")
        if not image:
            continue
        try:
            _candidate_url(image)
        except Exception:
            continue

        out.append(
            {
                "title": page.get("title", "").removeprefix("File:"),
                "page_url": page.get("fullurl", ""),
                "image_url": image,
                "image_source": "wikimedia-commons",
                "alt": page.get("title", "").removeprefix("File:"),
            }
        )
    return out


def _duckduckgo_vqd(query: str) -> str:
    """
    Obtain DuckDuckGo's transient image-search token.

    DDG's image JSON endpoint is not a formal public API, so this provider is
    best-effort and always has documented Wikimedia fallbacks.
    """
    url = "https://duckduckgo.com/?" + urllib.parse.urlencode(
        {"q": query, "iax": "images", "ia": "images"}
    )
    data, _, content_type = _request_bytes(
        url,
        headers={"Referer": "https://duckduckgo.com/"},
        max_bytes=2_000_000,
    )
    text = _decode(data, content_type)
    _check_challenge(text)

    patterns = [
        r"vqd=['\"]([^'\"]+)['\"]",
        r'"vqd"\s*:\s*"([^"]+)"',
        r"vqd=([0-9-]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return html.unescape(m.group(1))
    raise RuntimeError("DuckDuckGo image token was not found.")


def _duckduckgo_images(query: str, limit: int = 12) -> list[dict[str, str]]:
    vqd = _duckduckgo_vqd(query)
    params = {
        "l": "us-en",
        "o": "json",
        "q": query,
        "vqd": vqd,
        "f": ",,,,,",
        "p": "1",
    }
    url = "https://duckduckgo.com/i.js?" + urllib.parse.urlencode(params)
    payload = _json_request(
        url,
        headers={
            "Referer": "https://duckduckgo.com/",
            "Accept": "application/json",
        },
        max_bytes=4_000_000,
    )

    out: list[dict[str, str]] = []
    for item in payload.get("results", []):
        image = item.get("image") or ""
        page = item.get("url") or ""
        if not image:
            continue
        try:
            _candidate_url(image)
        except Exception:
            continue
        out.append(
            {
                "title": item.get("title", ""),
                "page_url": page,
                "image_url": image,
                "image_source": "duckduckgo-images",
                "alt": item.get("title", ""),
                "thumbnail_url": item.get("thumbnail", ""),
                "source_domain": item.get("source", ""),
            }
        )
        if len(out) >= limit:
            break
    return out


def _page_metadata_images(
    query: str,
    page_limit: int = 5,
    candidate_limit: int = 12,
) -> tuple[str, list[dict[str, str]], list[dict[str, str]]]:
    """
    Last-resort fallback: normal web search, then extract og:image/twitter:image
    from result pages. This was v15.14's ONLY image-discovery method.
    """
    search = web_search(query, limit=max(3, min(page_limit, 8)))
    state = WebState()
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()

    for result in search["results"][:page_limit]:
        state.check()
        page_url = result.get("url", "")
        if not page_url:
            continue
        try:
            for img in _page_image_candidates(page_url):
                u = img["image_url"]
                if u in seen:
                    continue
                seen.add(u)
                candidates.append(
                    {
                        "title": result.get("title", ""),
                        "page_url": page_url,
                        "image_url": u,
                        "image_source": "page-metadata:" + img.get("source", ""),
                        "alt": img.get("alt", ""),
                    }
                )
                if len(candidates) >= candidate_limit:
                    break
        except ProfileLocked:raise
        except WebLookupLimit as exc:
            # Preserve pages/images already obtained even if a later page
            # consumes the operation allowance.
            exc.details.update(images=candidates, search_results=search['results'])
            raise
        except Exception:
            continue
        if len(candidates) >= candidate_limit:
            break

    state.check()
    return search["provider"], search["results"], candidates


@_image_operation
def image_search(query: str, page_limit: int = 5, candidate_limit: int = 12) -> dict[str, Any]:
    """
    Find EXISTING public-web images.

    Broad image search and ordinary public-web image metadata run first.
    Wikipedia and Commons are additional providers, not a website allowlist.
    Page/text results are evidence only; they never count as image candidates.
    """
    query = " ".join(query.split())
    if not query:
        raise ValueError("Image-search query is empty.")

    candidate_limit = max(1, min(int(candidate_limit), 30))
    page_limit = max(1, min(int(page_limit), 8))
    state = WebState()
    candidates: list[dict[str, str]] = []
    seen: set[str] = set()
    providers_used: list[str] = []
    errors: list[str] = []
    error_details: list[dict[str, Any]] = []
    search_results: list[dict[str, str]] = []
    budget_exhausted = False

    def add(items: list[dict[str, str]], provider: str) -> None:
        for item in items:
            u = item.get("image_url", "")
            if not u or u in seen:
                continue
            try: _candidate_url(u)
            except ValueError: continue
            seen.add(u)
            if provider not in providers_used: providers_used.append(provider)
            candidates.append({**item, 'result_type': 'image_candidate',
                               'download_verified': False})
            if len(candidates) >= candidate_limit:
                break

    def run_provider(name, operation):
        nonlocal budget_exhausted
        if budget_exhausted: return
        state.check()
        try:
            cooldown = state.cooling('image:' + name)
        except ProfileLocked:raise
        except Exception:cooldown = None
        if cooldown:
            errors.append(name + ': ' + cooldown['message'])
            error_details.append(cooldown)
            return
        try:
            _IMAGE_BUDGET.get().check()
            items = operation()
            state.check()
            add(items, name)
        except ProfileLocked:raise
        except WebLookupLimit as exc:
            budget_exhausted = True
            add(exc.details.get('images', []), name)
            search_results.extend(exc.details.get('search_results', []))
            error_details.append({'provider':name, **exc.details})
            errors.append(name + ': ' + str(exc))
        except Exception as exc:
            detail = {'provider':name, **_web_error(exc)}
            error_details.append(detail)
            errors.append(name + ': ' + detail['message'])
            try:state.block('image:' + name, detail.get('retry_after_seconds',30), detail['message'])
            except ProfileLocked:raise
            except Exception:pass

    run_provider('duckduckgo-images', lambda:_duckduckgo_images(query, limit=candidate_limit))
    # A provider response may contain many candidates cheaply. Once several
    # actual URLs exist, let the caller inspect/refine instead of spending the
    # whole allowance filling an arbitrary list with unrelated fallback art.
    sufficient = min(candidate_limit, 3)
    if len(candidates) < sufficient:
        def metadata():
            nonlocal search_results
            _provider, search_results, images = _page_metadata_images(
                query, page_limit=page_limit, candidate_limit=sufficient-len(candidates))
            return images
        run_provider('public-page-images', metadata)
    if len(candidates) < sufficient:
        run_provider('wikipedia', lambda:_wikipedia_lead_images(query, limit=min(3,candidate_limit-len(candidates))))
    if len(candidates) < sufficient:
        run_provider('wikimedia-commons', lambda:_wikimedia_commons_images(query, limit=candidate_limit-len(candidates)))

    state.check()
    return {
        "provider": "+".join(providers_used) if providers_used else "none",
        "query": query,
        "images": candidates,
        "image_urls": [item['image_url'] for item in candidates],
        "result_type": "image_candidates",
        "image_count": len(candidates),
        "exact_match_verified": False,
        "lookup_limited": budget_exhausted,
        "network_requests": _IMAGE_BUDGET.get().requests,
        "note": "image_url links are unverified image candidates. Inspect title/alt/page_url for relevance. fetch PAGE_URL returns readable text plus discovered images/image_urls; download-image IMAGE_URL saves verified image bytes without repeating search. An exact semantic match is not verified.",
        "search_results": search_results,
        "provider_errors": errors,
        "provider_error_details": error_details,
    }


def _safe_filename(text: str, fallback: str = "web-image") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text.strip())
    text = text.strip("._-")
    return (text[:80] or fallback)


def _image_bytes_extension(data: bytes) -> str:
    """Reject text/error pages even when their URL or MIME type says image.

    This is bounded format-signature validation, not a full pixel decoder.
    """
    if len(data) >= 24 and data.startswith(b'\x89PNG\r\n\x1a\n') and data[12:16] == b'IHDR':return '.png'
    if len(data) >= 4 and data.startswith(b'\xff\xd8\xff'):return '.jpg'
    if len(data) >= 12 and data[:6] in (b'GIF87a',b'GIF89a'):return '.gif'
    if len(data) >= 16 and data[:4] == b'RIFF' and data[8:12] == b'WEBP':return '.webp'
    if len(data) >= 26 and data[:2] == b'BM':return '.bmp'
    if len(data) >= 24 and data[4:8] == b'ftyp' and any(data[n:n+4] in (b'avif',b'avis') for n in range(8,min(len(data),64),4)):return '.avif'
    raise ValueError('The server returned text or an unsupported image format, not a recognized image. No image file was saved.')


@_web_operation
def download_public_image(
    image_url: str,
    *,
    query: str = "web-image",
    output_root: str | None = None,
) -> dict[str, Any]:
    portable_root = ROOT
    context = capture(portable_root)
    def check_profile():
        if capture(portable_root) != context:
            raise ProfileLocked('The web-image login ended before publication')
    data, final_url, content_type = _request_bytes(
        image_url,
        headers={"Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
        max_bytes=20_000_000,
    )

    check_profile()
    if 'html' in content_type:_check_challenge(_decode(data[:30000], content_type))
    ext = _image_bytes_extension(data)
    folder = media_output(portable_root, output_root) if output_root else private_path(portable_root, 'Outputs/WebImages', context=context)
    scope = portable_root if folder.is_relative_to(portable_root) else folder
    _contained(scope, folder)
    require_space(portable_root, len(data)+1024**2, for_outputs=True)
    check_profile()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/(_safe_filename(query, 'web-image')+'_'+uuid.uuid4().hex[:12]+ext)
    part = path.with_suffix(path.suffix+'.part')
    identity = None
    published = False
    try:
        _contained(scope, part)
        with part.open('xb') as output:
            stat = os.fstat(output.fileno()); identity = (stat.st_dev,stat.st_ino)
            output.write(data); output.flush(); os.fsync(output.fileno())
        check_profile()
        _contained(scope, path)
        if path.exists():raise FileExistsError('Web image destination already exists')
        part.rename(path); published = True
        check_profile()
        rel = path.relative_to(private_path(portable_root, 'Outputs')).as_posix() if path.is_relative_to(private_path(portable_root,'Outputs')) else None
        preview_url = (_instance_url('preview', '/')+'/'.join(urllib.parse.quote(p,safe='') for p in rel.split('/'))) if rel else None
        preview_url = authenticated_preview_url(portable_root, preview_url) if preview_url and owned_preview(portable_root,_instance_port('preview')) else None
        check_profile()
        return {'path':str(path), 'files':[str(path)], 'source_url':final_url,
                'content_type':content_type, 'image_format':ext[1:], 'validation':'image_signature',
                'download_verified':True, 'exact_match_verified':False,
                'note':'Image bytes are already validated and saved; redundant file/PIL checks are unnecessary. This does not verify the pictured subject. Return the candidate and source; if the edit is unspecified, ask what to change. There is no ai_tools.py image-info command.',
                'preview_url':preview_url,
                'preview_markdown':f'![Web image]({preview_url})' if preview_url else None}
    except BaseException:
        if published:
            _contained(scope, path)
            if path.is_file() and not path.is_symlink():
                stat = path.lstat()
                if (stat.st_dev,stat.st_ino) == identity:path.unlink()
        raise
    finally:
        _contained(scope, part)
        if part.is_file() and not part.is_symlink():
            stat = part.lstat()
            if (stat.st_dev,stat.st_ino) == identity:part.unlink()


@_image_operation
def find_and_download_image(query: str, page_limit: int = 5) -> dict[str, Any]:
    state = WebState()
    # Keep a real download attempt available when discovery is slow. The full
    # operation still shares one 45-second/12-request ceiling.
    with _IMAGE_BUDGET.get().reserve(seconds=12, requests=3):
        found = image_search(query, page_limit=page_limit)
    errors: list[str] = []
    attempted_downloads = 0

    for candidate in found["images"][:3]:
        state.check()
        try:
            _IMAGE_BUDGET.get().check()
            attempted_downloads += 1
            downloaded = download_public_image(
                candidate["image_url"],
                query=query,
            )
            state.check()
            return {
                "provider": found["provider"],
                "query": query,
                "chosen": candidate,
                "download": downloaded,
                "files": downloaded['files'],
                "exact_match_verified": False,
                "alternatives": [
                    item for item in found["images"]
                    if item.get("image_url") != candidate.get("image_url")
                ][:5],
                "provider_errors": found.get("provider_errors", []),
            }
        except ProfileLocked:raise
        except ImageLookupLimit as exc:
            errors.append(str(exc)); break
        except Exception as exc:
            errors.append(f"{candidate['image_url']}: {exc}")

    details = []
    details.extend(found.get("provider_errors", []))
    details.extend(errors[:3])
    raise WebAccessError(
        "No downloadable public image was found for the query."
        + ((" Provider/download details: " + " | ".join(details[:6])) if details else ""),
        category='image_download_unavailable', query=query, retry_recommended=False,
        exact_match_verified=False, image_urls=found.get('image_urls', []),
        images=found['images'][:5], attempted_downloads=attempted_downloads,
        provider_error_details=found.get('provider_error_details',[]),
    )

@_web_operation
def fetch_url(url: str, max_chars: int = MAX_FETCH_CHARS) -> dict[str, Any]:
    max_chars = max(1000, min(int(max_chars), 50_000))
    state=WebState();cooldown_key='page:'+state.key(url,0)
    try:cooldown=state.cooling(cooldown_key)
    except ProfileLocked:raise
    except Exception:cooldown=None
    if cooldown:
        raise WebAccessError('This page is cooling down after its previous refusal. The page was not read.',
                             category='cooldown',retry_after_seconds=cooldown['retry_after_seconds'])
    try:
        data, final_url, content_type = _request_bytes(url)
        state.check()
    except ProfileLocked:raise
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        detail=_web_error(exc)
        try:state.block(cooldown_key,detail['retry_after_seconds'],detail['message'])
        except ProfileLocked:raise
        except Exception:pass
        raise WebAccessError(detail.pop('message')+' The page was not read; use another source or open it yourself.',
                             **detail) from exc
    lower_type = content_type.lower()
    try:
        _image_bytes_extension(data)
    except ValueError:
        if lower_type.startswith('image/'):raise
    else:
        state.check()
        return {'url':final_url, 'title':'', 'content_type':content_type, 'text':'',
                'result_type':'image', 'image_url':final_url, 'image_urls':[final_url],
                'note':'This URL is an image, not a text page. Use download-image to save and display it.'}

    if "application/pdf" in lower_type or final_url.lower().endswith(".pdf"):
        raise ValueError("PDF text extraction is not implemented in PortableAI web_tools yet.")

    text = _decode(data, content_type)
    try:_check_challenge(text)
    except WebAccessError as exc:
        try:state.block(cooldown_key,900,str(exc))
        except ProfileLocked:raise
        except Exception:pass
        raise
    title = ""
    images = []

    if "html" in lower_type or "<html" in text[:1000].lower():
        parser = PageTextParser()
        parser.feed(text)
        title = " ".join(" ".join(parser.title_parts).split())
        body = _clean_text(" ".join(parser.parts))
        images = [{**item, 'page_url':final_url, 'result_type':'image_candidate', 'download_verified':False}
                  for item in _html_image_candidates(text, final_url, max_candidates=12)]
    else:
        body = _clean_text(text)

    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "\n[truncated]"

    state.check()
    return {
        "url": final_url,
        "title": title,
        "content_type": content_type,
        "text": body,
        "full_page_fetched": True,
        "images": images,
        "image_urls": [item['image_url'] for item in images],
        "image_note": "These are candidates found in this page's metadata/img/srcset, not verified semantic matches or a complete browser rendering. Use download-image IMAGE_URL to verify bytes and save. JavaScript-only/blocked images may be absent; raw HTML or ad-hoc scraping is not needed for these returned candidates.",
    }


@_web_operation
def research(query: str, limit: int, fetch_count: int, max_chars: int) -> dict[str, Any]:
    search = web_search(query, limit=limit)
    state = WebState()
    pages = []
    limited = False
    for result in search["results"][: max(0, min(fetch_count, 5))]:
        state.check()
        try:
            page = fetch_url(result["url"], max_chars=max_chars)
            page["search_title"] = result.get("title", "")
            page["search_snippet"] = result.get("snippet", "")
            pages.append(page)
        except ProfileLocked:raise
        except Exception as exc:
            pages.append(
                {
                    "url": result["url"],
                    "search_title": result.get("title", ""),
                    "error": str(exc),
                    "fetch_error": _web_error(exc),
                    "full_page_fetched": False,
                    "source_type": "search_snippet_only",
                    "search_snippet": result.get("snippet", ""),
                }
            )
            if isinstance(exc, WebLookupLimit):
                limited = True
                break
    state.check()
    return {
        "provider": search["provider"],
        "query": query,
        "results": search["results"],
        "pages": pages,
        "provider_errors": search.get('provider_errors',[]),
        "cached_search": search.get('cached',False),
        "cache_age_seconds": search.get('cache_age_seconds',0),
        "lookup_limited": limited,
        "network_requests": _IMAGE_BUDGET.get().requests,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="PortableAI live web search and research")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("search", help="Search the live public web")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=DEFAULT_SEARCH_RESULTS)
    p.add_argument('--fresh',action='store_true',help='Bypass the five-minute result cache; provider cooldowns still apply')

    p = sub.add_parser("fetch", help="Fetch readable page text plus actual candidate image URLs from metadata/img/srcset")
    p.add_argument("url")
    p.add_argument("--max-chars", type=int, default=MAX_FETCH_CHARS)

    p = sub.add_parser("research", help="Search then fetch a few top public webpages")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=DEFAULT_SEARCH_RESULTS)
    p.add_argument("--fetch-count", type=int, default=2)
    p.add_argument("--max-chars", type=int, default=6000)

    p = sub.add_parser("image-search", help="Use real image providers to find existing public-web image candidates")
    p.add_argument("query")
    p.add_argument("--page-limit", type=int, default=5)

    p = sub.add_parser("image", help="Find and download an existing public-web image into Outputs\\WebImages")
    p.add_argument("query")
    p.add_argument("--page-limit", type=int, default=5)

    p = sub.add_parser("download-image", help="Safely download one public image URL into Outputs\\WebImages")
    p.add_argument("url")
    p.add_argument("--name", default="web-image")

    sub.add_parser("selftest", help="Run a small live-search diagnostic")

    args = parser.parse_args()

    try:
        if args.cmd == "search":
            result = web_search(args.query, args.limit, fresh=args.fresh)
            emit({"success": True, "tool": "web-search", **result})

        if args.cmd == "fetch":
            page = fetch_url(args.url, args.max_chars)
            emit({"success": True, "tool": "web-fetch", **page})

        if args.cmd == "research":
            result = research(args.query, args.limit, args.fetch_count, args.max_chars)
            emit({"success": True, "tool": "web-research", **result})

        if args.cmd == "image-search":
            result = image_search(args.query, args.page_limit)
            found = bool(result['images'])
            emit({"success": found, "tool": "web-image-search", **result,
                  **({} if found else {'error':'No image URLs found. Any search_results are text/source pages, not images.'})}, 0 if found else 1)

        if args.cmd == "image":
            result = find_and_download_image(args.query, args.page_limit)
            emit({"success": True, "tool": "web-image", **result})

        if args.cmd == "download-image":
            result = download_public_image(args.url, query=args.name)
            emit({"success": True, "tool": "web-download-image", **result})

        if args.cmd == "selftest":
            result = web_search("Python official documentation", 3, fresh=True)
            emit(
                {
                    "success": bool(result.get("results")),
                    "tool": "web-selftest",
                    "provider": result.get("provider"),
                    "result_count": len(result.get("results", [])),
                    "first_result": result.get("results", [None])[0],
                    "provider_errors":result.get('provider_errors',[]),
                }
            )

    except Exception as exc:
        emit({"success": False, "tool": f"web-{args.cmd}", "error": str(exc),"details":_web_error(exc)}, 1)


if __name__ == "__main__":
    main()
