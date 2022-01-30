# Support for export to PAWLS (https://github.com/allenai/pawls)

import json

from .bbox import BBox


class PawlsDocument:
    def __init__(self, pages):
        self.pages = pages

    @classmethod
    def from_json(cls, data):
        assert isinstance(data, list)
        pages = [
            PawlsPage.from_json(p) for p in data
        ]
        return cls(pages)


class PawlsPage:
    def __init__(self, width, height, index, tokens):
        self.width = width
        self.height = height
        self.index = index
        self.tokens = tokens

    @classmethod
    def from_json(cls, d):
        assert isinstance(d, dict)
        width = d['page']['width']
        height = d['page']['height']
        index = d['page']['index']
        tokens = []
        for i, t in enumerate(d['tokens']):
            tokens.append(PawlsToken.from_json(t, i, height))
        return cls(width, height, index, tokens)


class PawlsToken:
    def __init__(self, text, bbox, index):
        self.text = text
        self.bbox = bbox
        self.index = index

    def __str__(self):
        return (f'PawlsToken(text="{self.text}" bbox={self.bbox} '
                f'index={self.index})')

    @classmethod
    def from_json(cls, d, index, page_height):
        assert isinstance(d, dict)
        text = d['text']
        llx = d['x']
        y1 = d['y']
        width = d['width']
        height = d['height']
        urx = llx + width
        y2 = y1 + height
        # PAWLS y origin is page top; invert to get PDF coordinates.
        lly = page_height - y2
        ury = page_height - y1
        bbox = BBox(llx, lly, urx, ury)
        return cls(text, bbox, index)


def load_pawls_structure(json_path):
    """Load PDF structure created with `pawls preprocess pdfplumber`."""
    with open(json_path) as f:
        data = json.load(f)
    return PawlsDocument.from_json(data)
