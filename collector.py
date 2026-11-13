"""Suppress equivalent RPA-recorded portal exports before landing."""
import json
from html.parser import HTMLParser
from canon import canonicalize, Invalid


class _Capture(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.active = False
        self.parts = []
        self.exports = []

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.active = dict(attrs).get('id') == 'capture-graph'
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.active:
            self.exports.append(''.join(self.parts))
            self.active = False


def _reject_constant(value):
    raise ValueError('nonstandard JSON number')


def collect(pages, limit=100000):
    if type(pages) is not list:
        raise Invalid('PAGES')
    seen, kept, duplicates = {}, [], []
    for index, page in enumerate(pages):
        if type(page) is not str:
            raise Invalid('PAGE')
        parser = _Capture()
        parser.feed(page)
        parser.close()
        if len(parser.exports) != 1:
            raise Invalid('CAPTURE_SCRIPT')
        try:
            payload = json.loads(parser.exports[0], parse_constant=_reject_constant)
        except ValueError as error:
            raise Invalid('CAPTURE_JSON') from error
        if type(payload) is not dict or set(payload) != {'quads'}:
            raise Invalid('CAPTURE_JSON')
        code = canonicalize(payload['quads'], limit)['code']
        if code in seen:
            duplicates.append([index, seen[code]])
        else:
            seen[code] = index
            kept.append(index)
    return {'kept': kept, 'duplicate_of': duplicates}
