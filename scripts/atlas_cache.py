"""Identifica a origem de imagens derivadas, incluindo tiles citados no VRT."""
import hashlib
from pathlib import Path
from xml.etree import ElementTree


def source_signature(*paths, settings=()):
    digest = hashlib.sha256(repr(settings).encode())
    seen = set()

    def visit(path):
        path = Path(path).resolve()
        if path in seen:
            return
        seen.add(path)
        stat = path.stat()
        digest.update(repr((str(path), stat.st_size, stat.st_mtime_ns)).encode())
        if path.suffix.lower() == '.vrt':
            data = path.read_bytes()
            digest.update(data)
            for node in ElementTree.fromstring(data).iter('SourceFilename'):
                if node.text:
                    visit(path.parent / node.text if node.get('relativeToVRT') == '1' else node.text)
        elif path.suffix.lower() == '.csv':
            digest.update(path.read_bytes())

    for path in paths:
        visit(path)
    return digest.hexdigest()
