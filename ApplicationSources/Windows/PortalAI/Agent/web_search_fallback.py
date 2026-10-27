"""Bounded parsing of ordinary Bing search results; no browser/challenge bypass."""
import base64
import binascii
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlsplit


def result_url(href, validate):
    target = urljoin('https://www.bing.com/', href)
    parsed = urlsplit(target)
    if parsed.hostname in ('bing.com', 'www.bing.com'):
        if parsed.path != '/ck/a':
            raise ValueError('Search navigation is not a result URL')
        encoded = parse_qs(parsed.query).get('u', [''])[0]
        if not encoded.startswith('a1') or len(encoded) > 11000:
            raise ValueError('Unrecognized result redirect')
        value = encoded[2:]
        try:
            target = base64.b64decode(value + '=' * (-len(value) % 4), altchars=b'-_', validate=True).decode('utf-8')
        except (ValueError, UnicodeError, binascii.Error) as exc:
            raise ValueError('Invalid result redirect') from exc
    parsed = validate(target)
    if parsed.hostname in ('bing.com', 'www.bing.com'):
        raise ValueError('Search navigation is not a result URL')
    return target


class BingSearchParser(HTMLParser):
    """Keep organic result headings/snippets, excluding ads, scripts and navigation."""
    def __init__(self, validate, limit=12):
        super().__init__(convert_charrefs=True)
        self.validate = validate
        self.limit = max(1, min(int(limit), 12))
        self.results = []
        self.seen = set()
        self.current = None
        self.depth = 0
        self.hidden = 0
        self.heading = False
        self.title = False
        self.paragraph = False

    def finish(self):
        item = self.current
        if item and item['url'] and item['title'] and item['url'] not in self.seen and len(self.results) < self.limit:
            self.results.append({key: ' '.join(value.split())[:(8192 if key == 'url' else 2000)] for key, value in item.items()})
            self.seen.add(item['url'])
        self.current = None
        self.depth = 0
        self.heading = self.title = self.paragraph = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'noscript', 'template'):
            self.hidden += 1
        if self.hidden:
            return
        if tag == 'li' and 'b_algo' in attrs.get('class', '').split():
            self.finish()
            self.current = {'title': '', 'url': '', 'snippet': ''}
            self.depth = 1
            return
        if not self.current:
            return
        if tag == 'li':
            self.depth += 1
        if tag == 'h2' and self.depth == 1:
            self.heading = True
        if tag == 'a' and self.heading and not self.current['url']:
            try:
                self.current['url'] = result_url(attrs.get('href', ''), self.validate)
                self.title = True
            except ValueError:
                pass
        if tag == 'p' and self.depth == 1:
            self.paragraph = True

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'template') and self.hidden:
            self.hidden -= 1
            return
        if self.hidden or not self.current:
            return
        if tag == 'a':
            self.title = False
        if tag == 'h2':
            self.heading = False
        if tag == 'p':
            self.paragraph = False
        if tag == 'li':
            self.depth -= 1
            if self.depth <= 0:
                self.finish()

    def handle_data(self, text):
        if self.hidden or not self.current:
            return
        if self.title and len(self.current['title']) < 2000:
            self.current['title'] += text
        if self.paragraph and len(self.current['snippet']) < 2000:
            self.current['snippet'] += text
