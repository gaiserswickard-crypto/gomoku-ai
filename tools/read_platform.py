"""Read the user-selected public submission and its linked match records."""
import json
import re
import sys
import html as html_lib
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urljoin

class Element:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []
    def text(self):
        return ' '.join(c.text() if isinstance(c, Element) else c for c in self.children)
    def find(self, predicate):
        result = []
        for c in self.children:
            if isinstance(c, Element):
                if predicate(c): result.append(c)
                result.extend(c.find(predicate))
        return result

class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Element()
        self.stack = [self.root]
        self.feed(text)
    def handle_starttag(self, tag, attrs):
        node = Element(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append(node)
    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break
    def handle_data(self, data): self.stack[-1].children.append(data)

def clean(text): return ' '.join(text.split())

sys.stdout.reconfigure(encoding='utf-8')
BASE = 'http://192.168.180.56:18080'
OUT = Path(__file__).resolve().parents[1] / 'results' / 'platform'
OUT.mkdir(parents=True, exist_ok=True)

def fetch(path):
    url = urljoin(BASE, path)
    with urlopen(url, timeout=20) as response:
        html = response.read().decode('utf-8')
    # Discard the anonymous request's CSRF field; no account cookies are used.
    html = re.sub(r'("csrfToken"\s*:\s*)"[^"]*"', r'\1"[omitted]"', html)
    (OUT / (path.split('?')[0].rstrip('/').split('/')[-1] + '.html')).write_text(html, encoding='utf-8')
    return Document(html).root

if __name__ == '__main__':
    path = sys.argv[1]
    soup = fetch(path)
    if path.startswith('/submission/'):
        containers = soup.find(lambda n:n.attrs.get('id') == 'match_row_container')
        for row in containers[0].find(lambda n:n.tag == 'tr'):
            links = row.find(lambda n:n.tag == 'a' and n.attrs.get('href','').startswith('/match/'))
            print(json.dumps({'url':links[0].attrs['href'] if links else None,
                              'text':clean(row.text())},ensure_ascii=False))
        print('PAGINATION', [(clean(a.text()),a.attrs.get('href')) for a in soup.find(lambda n:n.tag=='a' and 'page=' in n.attrs.get('href',''))])
    else:
        print(clean(soup.text())[:14000])
        print('LINKS',json.dumps([{'label':clean(a.text()),'url':a.attrs.get('href')} for a in soup.find(lambda n:n.tag=='a' and 'href' in n.attrs)],ensure_ascii=False))
        print('SCRIPTS',json.dumps([{'src':s.attrs.get('src'),'inline':s.text()[:12000]} for s in soup.find(lambda n:n.tag=='script') if s.attrs.get('src') or 'UiContext' not in s.text()],ensure_ascii=False))
