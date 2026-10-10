"""Check repository-subpath assets and prevent accidental credential bundles."""
import json
import re
from pathlib import Path
from html.parser import HTMLParser

root = Path('site')
class Assets(HTMLParser):
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if key in ('src','href') and value and not value.startswith(('https://','#')):
                assert not value.startswith('/'), 'Root asset path breaks GitHub Pages subpath'
                assert (root / value).exists(), f'Missing asset: {value}'
Assets().feed((root/'index.html').read_text())
config = json.loads((root/'config.json').read_text())
assert set(config) == {'apiBaseUrl'}
for path in root.glob('*'):
    if path.is_file():
        text = path.read_text()
        assert not re.search(r'(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|BEGIN PRIVATE KEY)',text), f'Credential-like content: {path}'
print('Static assets, subpath links and configuration checks passed')
