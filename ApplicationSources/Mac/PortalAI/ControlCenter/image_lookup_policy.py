"""Progress-aware image lookup limits; unrelated requested tools remain available."""
from __future__ import annotations

import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit


class ImageLookupCycle:
    """Bound one user turn's web image work without terminating the whole task."""
    MAX_SECONDS = 180.0
    MAX_SEARCHES = 8
    MAX_INSPECTIONS = 6
    MAX_STALLED_SEARCHES = 2
    MIN_SEARCHES_BEFORE_STALL_STOP = 4
    MAX_DUPLICATES = 2
    SEARCH_ACTIONS = frozenset({'image', 'image-search', 'search', 'research'})

    def __init__(self, user_request=''):
        self.active = self.existing_image_intent(user_request)
        self.finalize = False
        self.queries = set()
        self.actions = set()
        self.searches = 0
        self.downloads = 0
        self.links = []
        self.source_links = []
        self.saved_files = []
        self.no_progress = 0
        self.duplicates = 0
        self.started_at = None
        self.reason = ''
        self.last_progress = ''
        self._seen_urls = set()
        self._inflight = None
        self._inspection_closed = False

    @staticmethod
    def existing_image_intent(text):
        if not isinstance(text, str):
            return False
        asset = r'\b(?:images?|photos?|pictures?|photographs?|screenshots?)\b'
        # Remove research concepts, not an entire mixed search-and-edit request.
        text = re.sub(asset + r'\s+(?:generation|classification|recognition|processing|editing|models?|tools?|formats?)\b',
                      'visual research topic', text, flags=re.I)
        lookups = re.finditer(r'\b(?:find|search|look\s+(?:up|for)|show|download|retrieve|get)\b[^.!?\n]{0,120}?' + asset,
                             text, re.I)
        for match in lookups:
            # "Show me how to generate an image" is not an existing-image request.
            if not re.search(r'\b(?:generate|create|draw|render|make|design|paint|edit)\b', match.group(), re.I):
                return True
        return False

    @staticmethod
    def request(name, args):
        if name != 'shell' or not isinstance(args, dict):
            return None
        command = args.get('command', '')
        if not isinstance(command, str):
            return None
        command = re.sub(r'(?i)Agent\\web_tools\.py', 'Agent/web_tools.py', command)
        try:
            from chat_model_switch import _argv
            parts = _argv(command)
        except (ValueError, OSError):
            return None
        script_index = 1
        # Accept the portable interpreter's common flags without treating
        # arbitrary shell/Python expressions as the documented direct route.
        while script_index < len(parts):
            if parts[script_index] in {'-B', '-I', '-s', '-u'}:
                script_index += 1
            elif parts[script_index:script_index + 2] == ['-X', 'utf8']:
                script_index += 2
            else:
                break
        if len(parts) < script_index + 3 or Path(parts[script_index].replace('\\', '/')).name != 'web_tools.py':
            return None
        action = parts[script_index + 1]
        if action not in ImageLookupCycle.SEARCH_ACTIONS | {'fetch', 'download-image'}:
            return None
        values = iter(parts[script_index + 2:])
        value = None
        for item in values:
            if item == '--':
                value = next(values, None)
                break
            if item == '--fresh':
                continue
            if item.startswith('--'):
                if '=' not in item:
                    next(values, None)
                continue
            value = item
            break
        if value is None:
            return None
        key = ' '.join(value.split()).casefold() if action in ImageLookupCycle.SEARCH_ACTIONS else value.strip()
        return action, key

    def _close(self, reason, *, all_lookup=False):
        self.finalize = True
        self._inspection_closed = self._inspection_closed or all_lookup
        if not self.reason or all_lookup:
            self.reason = reason

    def _check_elapsed(self):
        if self.started_at is not None and time.monotonic() - self.started_at >= self.MAX_SECONDS:
            self._close('The image lookup elapsed-time allowance has been reached.', all_lookup=True)

    def _evidence_retrieval_available(self):
        return (not self._inspection_closed and self.downloads < self.MAX_INSPECTIONS
                and (not self.finalize or bool(self._seen_urls)))

    def before(self, name, args):
        self._inflight = None
        request = self.request(name, args)
        # Lookup exhaustion is never permission to discard autoedit, science,
        # file or other requested tool calls in the same task or batch.
        if request is None:
            return None
        if request[0] in {'image', 'image-search', 'download-image'}:
            self.active = True
        if not self.active:
            return None
        self._check_elapsed()
        action, value = request
        search = action in self.SEARCH_ACTIONS
        if self.finalize:
            if search or not self._evidence_retrieval_available():
                return self.blocked()
            if value not in self._seen_urls:
                return self.blocked('Searches have finished. Only previously returned candidate image/source URLs may now be inspected or downloaded; this new URL was not executed.')
        if request in self.actions or (search and value in self.queries):
            self.duplicates += 1
            if self.duplicates >= self.MAX_DUPLICATES:
                self._close('Repeated image lookup attempts did not change the query or URL.')
            return self.blocked('This exact query or URL was already attempted. Change the query meaningfully or use the returned evidence; the duplicate was not executed.')
        if search and self.searches >= self.MAX_SEARCHES:
            self._close('The distinct image-search safety ceiling has been reached.')
            return self.blocked()
        if not search and self.downloads >= self.MAX_INSPECTIONS:
            self._close('The image page/download safety ceiling has been reached.', all_lookup=True)
            return self.blocked()
        if self.started_at is None:
            self.started_at = time.monotonic()
        self.actions.add(request)
        self._inflight = request
        if search:
            self.queries.add(value)
            self.searches += 1
        else:
            self.downloads += 1
        return None

    def blocked(self, message=None):
        retrieval = self._evidence_retrieval_available()
        lookup_closed = self.finalize and not retrieval
        next_step = (' Previously returned candidate URLs may still be inspected/downloaded within the remaining allowance.'
                     if self.finalize and retrieval else ' Use the completed evidence and state any uncertainty.')
        return json.dumps({
            'success': False, 'tool': 'image-lookup-boundary',
            'error': message or (self.reason + next_step),
            'exact_match_verified': False, 'image_urls': self.links[:12],
            'source_urls': self.source_links[:12], 'lookup_closed': lookup_closed,
            'searches_closed': self.finalize, 'known_candidate_retrieval_available': retrieval,
            'other_requested_tools_available': True,
            '_portableai': {'terminal_result': lookup_closed, 'scope': 'image_lookup_only'},
        }, ensure_ascii=True)

    @staticmethod
    def _public_link(value):
        if not isinstance(value, str) or any(ord(char) < 32 for char in value):
            return None
        value = value.strip()
        try:
            parsed = urlsplit(value)
        except ValueError:
            return None
        return value if parsed.scheme in {'http', 'https'} and parsed.netloc else None

    def _collect(self, data):
        # Inspect only known result fields; prose/error text does not invent URL
        # evidence. Keep source pages separate from actual image candidates.
        rows = [data]
        for name in ('details', 'chosen', 'download'):
            row = data.get(name)
            if isinstance(row, dict):
                rows.append(row)
        for row in list(rows):
            for name in ('images', 'alternatives', 'results', 'search_results', 'pages'):
                items = row.get(name)
                if isinstance(items, list):
                    rows.extend(item for item in items[:30] if isinstance(item, dict))
        images, sources = [], []
        for row in rows:
            candidates = row.get('image_urls')
            if isinstance(candidates, list):
                images.extend(candidates[:30])
            images.append(row.get('image_url'))
            sources.append(row.get('page_url'))
            if row.get('download_verified') is True:
                images.append(row.get('source_url'))
                if isinstance(row.get('path'), str) and row['path'] not in self.saved_files:
                    self.saved_files.append(row['path'])
            elif row.get('success') is not False and not row.get('error'):
                sources.extend((row.get('url'), row.get('source_url')))
        progress = 0
        for candidates, destination in ((images, self.links), (sources, self.source_links)):
            for candidate in candidates:
                url = self._public_link(candidate)
                if url is None:
                    continue
                if url not in destination:
                    destination.append(url)
                if url not in self._seen_urls:
                    self._seen_urls.add(url)
                    progress += 1
        return progress

    def record(self, name, args, result):
        request = self.request(name, args)
        if not self.active or request is None or request != self._inflight:
            return
        self._inflight = None
        try:
            data = result if isinstance(result, dict) else json.JSONDecoder().raw_decode(str(result).lstrip())[0]
        except (ValueError, TypeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        progress = self._collect(data)
        failed = data.get('success') is False or not data
        self.last_progress = (f'The last attempt returned {progress} new candidate image/source URLs.' if progress else
                              'The last attempt failed without new candidate URLs.' if failed else
                              'The last attempt returned no new candidate image/source URLs.')
        if request[0] in self.SEARCH_ACTIONS:
            self.no_progress = 0 if progress else self.no_progress + 1
            if self.no_progress >= self.MAX_STALLED_SEARCHES and self.searches >= self.MIN_SEARCHES_BEFORE_STALL_STOP:
                self._close('After several distinct query strategies, consecutive image searches produced no new candidate image/source URLs.')
            if self.searches >= self.MAX_SEARCHES:
                self._close('The distinct image-search safety ceiling has been reached.')
        if self.downloads >= self.MAX_INSPECTIONS:
            self._close('The image page/download safety ceiling has been reached.', all_lookup=True)
        # A provider's shorter per-operation limit does not discard useful
        # results or end a still-productive multi-step lookup.
        self._check_elapsed()

    def guidance(self):
        if not self.active or not self.actions:
            return ''
        self._check_elapsed()
        if self.finalize:
            retrieval = (' Previously returned candidate image/source URLs can still be inspected or downloaded '
                         f'({self.MAX_INSPECTIONS - self.downloads} page/download attempts remain within the elapsed allowance). '
                         'Do not start another search or introduce an arbitrary new URL.'
                         if self._evidence_retrieval_available() else ' No further web image lookup attempts remain.')
            return ('Image searches have finished for this turn: ' + self.reason + retrieval +
                    ' Summarize the actual candidates and uncertainty; do not invent an exact match. '
                    'Other requested actions, including editing a downloaded image, '
                    'remain available and must be executed through their tools before claiming completion.')
        return (f'Image lookup progress: {self.searches}/{self.MAX_SEARCHES} distinct searches, '
                f'{self.downloads}/{self.MAX_INSPECTIONS} page/download attempts. ' + self.last_progress +
                ' Stop when evidence is adequate. If it is inadequate, make a meaningful broader/narrower query or inspect '
                'a credible returned page; check a possibly misspelled name/event using evidence and do not silently substitute a different subject. '
                'Do not repeat an attempted query. fetch PAGE_URL supplies page text plus images/image_urls from metadata/img/srcset; '
                'download-image IMAGE_URL downloads that candidate without repeating search. Source pages are not image URLs, '
                'and downloading verifies image bytes, not an exact semantic match. The elapsed allowance limits new lookup '
                'attempts, not an already-running model response. Continue other requested tool work normally.')

    def fallback(self, synthesis_error=None):
        text = 'The image lookup stopped. An exact match has not been verified.'
        if synthesis_error:
            text += ' Qwen could not finish summarizing the completed lookup (' + str(synthesis_error) + ').'
        if self.links:
            text += '\n\nActual image candidates:\n' + '\n'.join('- ' + url for url in self.links[:12])
        else:
            text += ' No usable image URL was returned.'
        if self.source_links:
            text += '\n\nSource pages (not verified image URLs):\n' + '\n'.join('- ' + url for url in self.source_links[:8])
        if self.saved_files:
            text += '\n\nDownloaded files:\n' + '\n'.join('- ' + path for path in self.saved_files[:6])
        return text
