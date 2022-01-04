#!/usr/bin/env python3

# Annotate PDF files based on their logical structure.

import sys
import io

from collections import defaultdict
from argparse import ArgumentParser

from PyPDF2 import PdfFileWriter, PdfFileReader

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import inch
from reportlab.lib.colors import Color, black, white
from reportlab.pdfbase.pdfmetrics import getFont, stringWidth

from pdfminer.layout import LTChar, LTPage, LTFigure, LTRect, LTCurve, LTLine
from pdfminer.utils import bbox2str

from taggedpdf import TaggedPdf
from taggedpdf.bbox import BBox
from taggedpdf.layout import split_into_columns
from taggedpdf.utils import clean_xml_text, clean_xml_attr
from taggedpdf.logger import logger


def argparser():
    ap = ArgumentParser()
    ap.add_argument(
        '--no-text-bbox-trim',
        default=False,
        action='store_true',
        help='do not trim bounding boxes of text elements'
    )
    ap.add_argument(
        '--no-table-bbox-extension',
        default=False,
        action='store_true',
        help='do not extend bounding boxes of tables to outline'
    )
    ap.add_argument(
        '--no-crop',
        default=False,
        action='store_true',
        help='do not crop annotations to page cropboxes'
    )
    ap.add_argument(
        '--keep-overlaps',
        default=False,
        action='store_true',
        help='do not eliminate overlapping annotations'
    )
    ap.add_argument(
        '--include-content',
        default=False,
        action='store_true',
        help='include content items in output (XML output only)'
    )
    ap.add_argument(
        '--format',
        choices={ 'pdf', 'xml' },
        default='pdf',
        help='output format'
    )
    ap.add_argument('input')
    ap.add_argument('output')
    return ap


# Mapping from structure types to annotation labels
STRUCT_TYPE_TO_LABEL_MAP = {
    'P': 'Paragraph',
    'LI': 'ListItem',
    'H1': 'Title',
    'H2': 'Title',
    'H3': 'Title',
    'H4': 'Title',
    'H5': 'Title',
    'H6': 'Title',
    'TOC': 'TableOfContents',
    'TOCI': 'TocItem',
    'Table': 'Table',
    'Figure': 'Figure',
    'Footnote': 'Footnote',
    'Note': 'Footnote',
}


# Set of structure types that are annotated
ANNOTATED_TYPES = set(STRUCT_TYPE_TO_LABEL_MAP.keys())


# Set of structure types that can potentially span multiple columns
MULTICOLUMN_STRUCT_TYPES = { 'P', 'LI' }


# Set of annotation labels with trimmable text boxes
TRIMMABLE_STRUCT_TYPES = {
    'P',
    'H1',
    'H2',
    'H3',
    'H4',
    'H5',
    'H6',
    'Note',
    # consider also:
    # 'TableOfContents',
    # 'TocItem',
    # 'Figure',
}


# Structure types to recurse into
STRUCT_TYPE_TO_RECURSE_INTO = {
    'Document',
    'NonStruct',
    'Part',
    'Art',
    'Sect',
    'Div',
    'P',
    'L',
    'Unknown',
}


# Colors for annotations
LABEL_TO_HEX_COLOR_MAP = {
    'Paragraph': '#24DD24',
    'Title': '#6FDECD',
    'ListItem': '#D0EC37',
    'Table' : '#EC3737',
    'TableOfContents': '#DDBD24',
    'TocItem': '#CCAD14',
    'Figure': '#375BEC',
    'Reference': '#EC9937',
    'Footnote': '#777777',
    'Note': '#777777',
    'Caption': '#E186C0',
}


LABEL_TO_COLOR_MAP = {
    k: (int(v[1:3],16)/255, int(v[3:5],16)/255, int(v[5:7],16)/255)
    for k, v in LABEL_TO_HEX_COLOR_MAP.items()
}


# Number of units to expand minimal annnotation bboxes by
EXPAND_BBOX_BY = {
    'Paragraph': 3,
    'ListItem': 3,
    'Title': 3,
    'TableOfContents': 3,
    'Footnote': 2,    # assume slightly smaller font than usual
}


LABEL_FONT_NAME = 'Courier'
LABEL_FONT_SIZE = 6


class Annotation:
    def __init__(self, type_, bbox, page, layout_items):
        assert bbox is not None
        self.type = type_
        self.bbox = bbox
        self.page = page
        self.layout_items = layout_items

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
            f' page="{self.page}"'
            f' bbox="{self.bbox.coord_str()}"'
        )
        if not include_content:
            return s + '/>'
        else:
            s += '>\n'
            for i in self.layout_items:
                s += f'  {layout_item_xml_string(i)}\n'
            s += '</annotation>'
            return s

    def __str__(self):
        return f'Annotation(page={self.page} type={self.type} bbox={self.bbox})'


def add_labelled_rect(c, llx, lly, urx, ury, label, stroke_color, fill_color,
                      label_above=False):
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
    c.rect(llx, box_lly, text_width+1, LABEL_FONT_SIZE, fill=True)

    # label
    c.setFont(LABEL_FONT_NAME, LABEL_FONT_SIZE)
    c.setFillColor(black)
    text_y = box_lly+0.60*LABEL_FONT_SIZE-2
    c.drawString(llx+1, text_y, label)


def layout_item_xml_string(item):
    if isinstance(item, LTChar):
        return (
            f'<char'
            f' font={clean_xml_attr(item.fontname)}'
            f' bbox="{bbox2str(item.bbox)}"'
            f' colourspace="{item.ncs.name}"'
            f' ncolour="{item.graphicstate.ncolor}"'
            f' size="{item.size:.3f}">'
            f'{clean_xml_text(item.get_text())}'
            f'</char>'
        )
    else:
        logger.warning(f'TODO {type(item).__name__}')
        return ''


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
        add_labelled_rect(
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


def _annotations_for_node(page, node, args):
    type_ = str(node.struct_type)[1:]
    content = node.get_content(page, recursive=True)

    if node.get_bbox(page) is None:
        pass
    elif not content:
        logger.warning(f'no content for {type_} on page {page}')
        pass
    elif type_ not in ANNOTATED_TYPES:
        pass
    elif type_ not in MULTICOLUMN_STRUCT_TYPES:
        yield Annotation(type_, node.get_bbox(page), page, content)
    else:
        # potentially multicolumn
        columns = split_into_columns(
            node.get_content(page, recursive=True),
            node.get_bbox(page)
        )
        if len(columns) > 1:
            print(f'{len(columns)} columns on page {page} for {type_}')
            print(f'"{node.get_content_text(page, recursive=True)}"')
        for items in columns:
            bbox = BBox.from_layout_items(items)
            yield Annotation(type_, bbox, page, items)


def _get_annotations(page, node, args):
    yield from _annotations_for_node(page, node, args)
    type_ = str(node.struct_type)[1:]
    if type_ in STRUCT_TYPE_TO_RECURSE_INTO:
        for child in node.children:
            yield from _get_annotations(page, child, args)


def find_overlaps(annotations):
    overlaps = []
    for i in range(len(annotations)):
        for j in range(i+1, len(annotations)):
            a1, a2 = annotations[i], annotations[j]
            if a1.bbox.overlaps(a2.bbox):
                overlaps.append((a1, a2))
    return overlaps


def find_duplicates(page, overlaps, ignore=None):
    if ignore is None:
        ignore = set()
    duplicates = set()
    for a1, a2 in overlaps:
        if a1.bbox == a2.bbox and a1 not in ignore and a2 not in ignore:
            duplicates.add(a2)    # arbitrary choice
    return duplicates


def find_contained(page, overlaps, ignore=None):
    if ignore is None:
        ignore = set()
    contained = set()
    for a1, a2 in overlaps:
        if a1.bbox == a2.bbox:
            pass    # identical bboxes
        elif a1.bbox.contains(a2.bbox) and a1 not in ignore:
            contained.add(a2)
        elif a2.bbox.contains(a1.bbox) and a2 not in ignore:
            contained.add(a1)
    return contained


def eliminate_overlaps(page, annotations):
    overlaps = find_overlaps(annotations)

    eliminated = find_duplicates(page, overlaps)
    eliminated |= find_contained(page, overlaps, eliminated)

    annotations = [a for a in annotations if a not in eliminated]

    # remaining overlaps

    for i in range(len(annotations)):
        for j in range(i+1, len(annotations)):
            a1, a2 = annotations[i], annotations[j]
            if a1.bbox.overlaps(a2.bbox):
                print(
                    'OVERLAP: page', page,
                    a1.type, a2.type,
                    a1.bbox.jaccard(a2.bbox),
                    a1.bbox.relative_overlap(a2.bbox),
                    a1.bbox.contains(a2.bbox),
                    a2.bbox.relative_overlap(a1.bbox),
                    a2.bbox.contains(a1.bbox)
                )

    return annotations


def extend_table_bboxes(page, annotations, nonmarked, margin=4):
    # Consider lines and recangles that were not marked content as
    # candidate table outlines
    candidates = [i for i in nonmarked if isinstance(i, (LTLine, LTRect))]
    tables = [a for a in annotations if a.type == 'Table']
    while True:
        extended = False

        # Find potential outline items that overlap exactly one table,
        # keep non-overlapping for subsequent extension. (Discard
        # candidates that overlap multiple tables to avoid introducing
        # new overlaps)
        outline_items_by_table, remaining = defaultdict(list), []
        for item in candidates:
            item_bbox = BBox.from_layout_item(item)
            overlaps = [
                table for table in tables
                if item_bbox.overlaps(table.bbox.padded(margin))
            ]
            if not overlaps:
                remaining.append(item)
            elif len(overlaps) == 1:
                table = overlaps[0]
                outline_items_by_table[table].append(item)

        # Apply extensions (TODO: avoid if this increases overlaps)
        for table, outline_items in outline_items_by_table.items():
            outline_bbox = BBox.from_layout_items(outline_items)
            bbox_with_outline = table.bbox.union(outline_bbox)
            relative_area = bbox_with_outline.area / table.bbox.area
            if relative_area > 1.0:
                if relative_area > 1.5:
                    # Maybe a bit much?
                    logger.warning(f'extended table to {relative_area:.1%} '
                                   f'on page {page}')
                table.bbox = bbox_with_outline
                extended = True

        if not extended:
            break

        candidates = remaining

    return annotations


def get_annotations(page, tagged_pdf, args):
    annotations = [
        annotation for node in tagged_pdf.struct_tree_root.children
        for annotation in _get_annotations(page, node, args)
    ]

    if not args.no_text_bbox_trim:
        trimmed_annotations = []
        for a in annotations:
            if a.type in TRIMMABLE_STRUCT_TYPES:
                a.trim_bbox()
            if a.bbox is not None:
                trimmed_annotations.append(a)
        annotations = trimmed_annotations

    if not args.no_crop:
        cropbox = tagged_pdf.get_cropbox(page)
        cropped_annotations = []
        for a in annotations:
            a.crop(cropbox)
            if a.bbox is not None:
                cropped_annotations.append(a)
        annotations = cropped_annotations

    if not args.keep_overlaps:
        annotations = eliminate_overlaps(page, annotations)

    if not args.no_table_bbox_extension:
        nonmarked = tagged_pdf.nonmarked_by_page[page]
        annotations = extend_table_bboxes(page, annotations, nonmarked)

    return annotations


def can_annotate(pdf, fn):
    # check that we have a tagged PDF
    if pdf.struct_tree_root is None:
        logger.warning(f'cannot annotate {fn}: no StructTreeRoot')
        return False
    elif pdf.mark_info is None:
        logger.warning('cannot annotate {fn}: no MarkInfo')
        return False
    elif not pdf.mark_info.marked:
        logger.warning('cannot annotate {fn}: not marked')
        return False
    elif pdf.struct_tree_root.parent_tree is None:
        logger.warning('cannot annotate {fn}: no parent tree')
        return False
    else:
        return True


def annotate_to_pdf(infn, outfn, tagged_pdf, args):
    # write marked PDF to output
    in_pdf = PdfFileReader(open(infn, 'rb'))
    out_pdf = PdfFileWriter()
    for page_idx, page in enumerate(in_pdf.pages):
        print(f'processing page {page_idx} ...', file=sys.stderr, flush=True)
        annotations = get_annotations(page_idx, tagged_pdf, args)
        if annotations:
            ann_pdf = render_annotations(annotations)
            ann_page = ann_pdf.getPage(0)
            page.mergePage(ann_page)
        out_pdf.addPage(page)
    with open(outfn, 'wb') as output:
        out_pdf.write(output)


def annotate_to_xml(infn, outfn, tagged_pdf, args):
    with open(outfn, 'w') as out:
        print(f'<document>', file=out)
        for page_idx in range(tagged_pdf.page_count):
            print(f'  <page index="{page_idx}">', file=out)
            for a in get_annotations(page_idx, tagged_pdf, args):
                for s in a.xml_string(args.include_content).splitlines():
                    #print(f'    {a.xml_str()}', file=out)
                    print(f'    {s}', file=out)
            print(f'  </document>', file=out)
        print(f'</document>', file=out)


def annotate(infn, outfn, args):
    tagged_pdf = TaggedPdf(infn)

    if not can_annotate(tagged_pdf, infn):
        return

    if args.format == 'pdf':
        return annotate_to_pdf(infn, outfn, tagged_pdf, args)
    elif args.format == 'xml':
        return annotate_to_xml(infn, outfn, tagged_pdf, args)
    else:
        raise NotImplementedError(f'format {args.format}')


def main(argv):
    args = argparser().parse_args(argv[1:])

    try:
        annotate(args.input, args.output, args)
    except Exception as e:
        print(f'{args.input}: ERROR: {e}')
        raise


if __name__ == '__main__':
    sys.exit(main(sys.argv))
