import io

from PyPDF2 import PdfFileReader

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import inch
from reportlab.lib.colors import Color, black, white
from reportlab.pdfbase.pdfmetrics import getFont, stringWidth

from .bbox import BBox
from .config import (
    COCO_CATEGORIES, STRUCT_TYPE_TO_LABEL_MAP,
    LABEL_TO_COLOR_MAP, LABEL_TO_HEX_COLOR_MAP,
    LABEL_FONT_NAME, LABEL_FONT_SIZE
)


TYPE_TO_COCO_CATEGORY_ID = { c['name']: c['id'] for c in COCO_CATEGORIES }


class Annotation:
    def __init__(self, type_, bbox, page, layout_items=None):
        assert bbox is not None
        if layout_items is None:
            layout_items = []
        self.type = type_
        self.bbox = bbox
        self.page = page
        self.layout_items = layout_items
        self.tokens = []

    def text_content(self):
        texts = []
        for i in self.layout_items:
            try:
                texts.append(i.get_text())
            except:
                pass
        return ''.join(texts)

    def crop(self, cropbox):
        cropped_items = []
        for item in self.layout_items:
            bbox = cropbox.intersection(item.bbox)
            if bbox is not None:
                cropped_items.append(item)
        if cropped_items == self.layout_items:
            # If no item was cropped, just crop the bbox
            self.bbox = cropbox.intersection(self.bbox)
        else:
            # Some items were cropped, redo bbox
            self.layout_items = cropped_items
            self.bbox = BBox.from_layout_items(self.layout_items)
            if self.bbox is not None:
                self.bbox = cropbox.intersection(self.bbox)

    def trim_bbox(self):
        trimmed_items = []
        for item in self.layout_items:
            try:
                text = item.get_text()
            except:
                continue
            if text and not text.isspace():
                trimmed_items.append(item)
        self.layout_items = trimmed_items
        self.bbox = BBox.from_layout_items(self.layout_items)

    def xml_string(self, include_content=False):
        type_ = STRUCT_TYPE_TO_LABEL_MAP.get(self.type, self.type)
        s = (
            f'<annotation type="{type_}"'
            #f' page="{self.page}"'    # this is redundant
            f' bbox="{self.bbox.coord_str()}"'
        )
        if not include_content:
            s =+ '/>'
        else:
            s += '>\n'
            for i in self.layout_items:
                s += f'  {layout_item_xml_string(i)}\n'
            s += '</annotation>'
        return s

    def coco_category_id(self):
        type_ = STRUCT_TYPE_TO_LABEL_MAP.get(self.type, self.type)
        return TYPE_TO_COCO_CATEGORY_ID[type_]

    def pawls_dict(self, page_height):
        label_text = STRUCT_TYPE_TO_LABEL_MAP.get(self.type, self.type)
        label_color = LABEL_TO_HEX_COLOR_MAP.get(label_text, '#FF0000')
        return {
            'id': str(uuid.uuid4()),
            'page': self.page,
            'label': {
                'text': label_text,
                'color': label_color
            },
            'bounds': {
                'left': self.bbox.llx,
                'right': self.bbox.urx,
                'top': page_height-self.bbox.ury,
                'bottom': page_height-self.bbox.lly
            },
            'tokens': [
                {
                    'pageIndex': self.page,
                    'tokenIndex': t.index
                }
                for t in self.tokens
            ]
        }

    def __lt__(self, other):
        # TODO implement sensible comparison
        return self.bbox.area < other.bbox.area
        
    def __str__(self):
        return f'Annotation(page={self.page} type={self.type} bbox={self.bbox})'


def _add_labelled_rect(c, llx, lly, urx, ury, label, stroke_color, fill_color,
                      label_above=True, label_right=True):
    # primary rectangle
    c.setStrokeColor(stroke_color)
    c.setFillColor(fill_color)
    c.rect(llx, lly, urx-llx, ury-lly, fill=True)

    # text background rectangle
    text_width = stringWidth(label, LABEL_FONT_NAME, LABEL_FONT_SIZE)
    c.setFillColor(white)
    if label_above:
        box_lly = ury
    else:
        box_lly = ury-LABEL_FONT_SIZE    # label inside
    if label_right:
        box_llx = urx-(text_width+1)
    else:
        box_llx = llx
    c.rect(box_llx, box_lly, text_width+1, LABEL_FONT_SIZE, fill=True)

    # label
    c.setFont(LABEL_FONT_NAME, LABEL_FONT_SIZE)
    c.setFillColor(black)
    text_y = box_lly+0.60*LABEL_FONT_SIZE-2
    c.drawString(box_llx+1, text_y, label)


def render_annotations(annotations):
    data = io.BytesIO()
    c = canvas.Canvas(data, pagesize=A4)    # TODO pagesize
    for a in annotations:
        label = STRUCT_TYPE_TO_LABEL_MAP.get(a.type, a.type)
        base_color = LABEL_TO_COLOR_MAP.get(label, (0,0,0))
        #if a.node.struct_type != a.node.original_struct_type:
        #    label += f' ({a.node.original_struct_type})'
        try:
            text = a.node.get_content_text(a.page, recursive=True)
        except:
            text=''
        stroke_color = Color(*base_color, alpha=0.75)
        fill_color = Color(*base_color, alpha=0.5)
        _add_labelled_rect(
            c,
            a.bbox.llx,
            a.bbox.lly,
            a.bbox.urx,
            a.bbox.ury,
            label,
            stroke_color,
            fill_color
        )
    c.save()
    data.seek(0)
    return PdfFileReader(data)
