#!/usr/bin/env python3

# Annotate PDF files based on their logical structure.

import sys
import re
import json
import uuid

from collections import defaultdict
from argparse import ArgumentParser

from pdfminer.layout import LTLine, LTRect
from PyPDF2 import PdfFileWriter, PdfFileReader

from taggedpdf import TaggedPdf
from taggedpdf.bbox import BBox
from taggedpdf.ltitem import layout_item_xml_string
from taggedpdf.layout import split_into_columns
from taggedpdf.pawls import load_pawls_structure
from taggedpdf.utils import file_sha256
from taggedpdf.annotation import Annotation, render_annotations
from taggedpdf.config import COCO_CATEGORIES, STRUCT_TYPE_TO_LABEL_MAP
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
        '--no-captions',
        default=False,
        action='store_true',
        help='do not assign Caption labels'
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
        '--pawls-structure',
        default=None,
        metavar='JSON',
        help='PAWLS pdf_structure.json for document (PAWLS output only)'
    )
    ap.add_argument(
        '--format',
        choices={ 'pdf', 'xml', 'pawls', 'coco' },
        default='pdf',
        help='output format'
    )
    ap.add_argument('input')
    ap.add_argument('output')
    return ap


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
    'Caption',
    # consider also:
    # 'TableOfContents',
    # 'TocItem',
    # 'Figure',
}


# Structure types to recurse into for generating annotations
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


# Structure types that may have captions
STRUCT_TYPES_WITH_CAPTIONS = {
    'Table',
    'Figure',
}


# Structure type to assign to captions
CAPTION_STRUCT_TYPE = 'Caption'


# Number of units to expand minimal annnotation bboxes by
EXPAND_BBOX_BY = {
    'Paragraph': 3,
    'ListItem': 3,
    'Title': 3,
    'TableOfContents': 3,
    'Footnote': 2,    # assume slightly smaller font than usual
}


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


CAPTION_STRING_RE = re.compile(r'''
^\s*
(
Figure|FIGURE|
Fig\.|FIG\.|
Chart|CHART|
Kaava|KAAVA|
Picture|PICTURE|
Table|TABLE|
Kuva|KUVA|
Kaavio|KAAVIO|
Kuvio|KUVIO|
Taulukko|TAULUKKO|
Bild|BILD|
Figur|FIGUR|
Tabell|TABELL
)
\s+\d+
''', re.VERBOSE)


def is_caption_text(string):
    m = CAPTION_STRING_RE.search(string)
    if m:
        logger.info(f'marking as Caption: "{string}" ("{m.group(1)}")')
        return True
    else:
        return False


def assign_caption_labels(page, annotations):
    for a in annotations:
        if a.type not in STRUCT_TYPES_WITH_CAPTIONS:
            continue
        candidates = [
            c for c in annotations
            if c is not a and c.bbox.horizontally_overlaps(a.bbox)
        ]
        above = [c for c in candidates if c.bbox.is_above(a.bbox)]
        below = [c for c in candidates if c.bbox.is_below(a.bbox)]
        above.sort(key=lambda c: c.bbox.vertical_distance(a.bbox))
        below.sort(key=lambda c: c.bbox.vertical_distance(a.bbox))
        if above and is_caption_text(above[0].text_content()):
            above[0].type = CAPTION_STRUCT_TYPE
        elif below and is_caption_text(below[0].text_content()):
            below[0].type = CAPTION_STRUCT_TYPE
    return annotations


def get_annotations(page, tagged_pdf, args):
    annotations = [
        annotation for node in tagged_pdf.struct_tree_root.children
        for annotation in _get_annotations(page, node, args)
    ]

    if not args.no_captions:
        annotations = assign_caption_labels(page, annotations)

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
                    print(f'    {s}', file=out)
            print(f'  </page>', file=out)
        print(f'</document>', file=out)


def annotate_to_pawls(infn, outfn, tagged_pdf, args):
    if args.pawls_structure is None:
        print(
            'Please provide the path to the pdf_structure.json generated'
            'by `pawls preprocess pdfplumber` with --pawls-structure',
            file=sys.stderr
        )
        return None
    pawls_document = load_pawls_structure(args.pawls_structure)
    if len(pawls_document.pages) != tagged_pdf.page_count:
        raise ValueError('page count mismatch')

    pawls_annotations = []
    for page_idx in range(tagged_pdf.page_count):
        pawls_page = pawls_document.pages[page_idx]
        annotations = get_annotations(page_idx, tagged_pdf, args)

        # Find annotation-token overlaps and assign tokens to the
        # annotation with which they have maximal relative overlap.
        tokens_by_annotation = defaultdict(list)
        for token in pawls_page.tokens:
            overlaps = []
            for a in annotations:
                overlap = token.bbox.relative_overlap(a.bbox)
                if overlap:
                    overlaps.append((overlap, a))
            if overlaps:
                a = sorted(overlaps, reverse=True)[0][1]
                a.tokens.append(token)

        for a in annotations:
            # PAWLS applies some padding (see preannotate.py), match
            a.bbox = a.bbox.padded(3)    # TODO parameterize
            pawls_annotations.append(a.pawls_dict(pawls_page.height))

    with open(outfn, 'w') as out:
        data = { 'annotations': pawls_annotations, 'relations': [] }
        json.dump(data, out)


def annotate_to_coco(infn, outfn, tagged_pdf, args):
    paper_id = 0
    coco = {
        'annotations': [],
        'categories': COCO_CATEGORIES,
        'images': [],
        'papers': [
            {
                'id': paper_id,
                'pages': tagged_pdf.page_count,
                'paper_sha': file_sha256(infn),
            }
        ],
    }
    next_ann_id = 0
    for page_idx in range(tagged_pdf.page_count):
        page_id = page_idx
        page_size = tagged_pdf.get_mediabox(page_idx)
        coco['images'].append({
            'id': page_id,
            'page_number': page_idx,
            'paper_id': paper_id,
            'width': page_size.width,
            'height': page_size.height,
        })
        for a in get_annotations(page_idx, tagged_pdf, args):
            coco['annotations'].append({
                'id': next_ann_id,
                'image_id': page_idx,
                'category_id': a.coco_category_id(),
                'bbox': a.bbox.padded(3).to_coco(page_size.height),
                'area': a.bbox.area,
                'iscrowd': False,
            })
            next_ann_id += 1
    with open(outfn, 'w') as out:
        json.dump(coco, out, indent=2)


def annotate(infn, outfn, args):
    tagged_pdf = TaggedPdf(infn)

    if not can_annotate(tagged_pdf, infn):
        return

    if args.format == 'pdf':
        return annotate_to_pdf(infn, outfn, tagged_pdf, args)
    elif args.format == 'xml':
        return annotate_to_xml(infn, outfn, tagged_pdf, args)
    elif args.format == 'pawls':
        return annotate_to_pawls(infn, outfn, tagged_pdf, args)
    elif args.format == 'coco':
        return annotate_to_coco(infn, outfn, tagged_pdf, args)
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
