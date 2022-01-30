#!/usr/bin/env python3

import sys
import json
import logging

import numpy as np
import pdf2image
import layoutparser

from argparse import ArgumentParser

from PyPDF2 import PdfFileWriter, PdfFileReader

from taggedpdf.bbox import BBox
from taggedpdf.pawls import PawlsDocument
from taggedpdf.pdfplumber import preprocess_with_pdfplumber
from taggedpdf.utils import file_sha256
from taggedpdf.annotation import Annotation, render_annotations
from taggedpdf.config import COCO_CATEGORIES
from taggedpdf.logger import logger


DEFAULT_LABELS = { c['id']: c['name'] for c in COCO_CATEGORIES }


CATEGORY_NAME_TO_ID = { c['name']: c['id'] for c in COCO_CATEGORIES }


def argparser():
    ap = ArgumentParser()
    ap.add_argument(
        'model',
        help='Layout Parser model (PyTorch PT/PTH file)'
    )
    ap.add_argument(
        'config',
        help='model configuration (YAML file)'
    )
    ap.add_argument(
        '--threshold',
        type=float,
        default=0.5,
        help='minimum prediction confidence'
    )
    ap.add_argument(
        '--labels',
        metavar='JSON',
        default=None
    )
    ap.add_argument(
        '--verbose',
        default=False,
        action='store_true'
    )
    ap.add_argument(
        '--format',
        choices={ 'pdf', 'xml', 'pawls', 'coco' },
        default='coco',
        help='output format'
    )
    ap.add_argument('input')
    ap.add_argument('output')
    return ap


def show_layout(image, layout):
    image = layoutparser.draw_box(
        image,
        layout,
        box_width=5,
        box_alpha=0.25,
#        color_map=COLOR_MAP,
        show_element_type=True,
        id_font_size=24
    )
    image.show()


def assign_tokens_to_blocks(page, layout):
    layout_bboxes = [
        BBox.from_layoutparser_block(b, page.height) for b in layout
    ]
    # Score layout blocks based on prediction confidence and overlap
    # and assign each token to the top-scoring block.
    block_tokens, unassigned = [[] for _ in layout], []
    for token in page.tokens:
        block_scores = []
        for block, bbox in zip(layout, layout_bboxes):
            overlap = token.bbox.relative_overlap(bbox)
            block_scores.append((block, block.score * overlap))
        idx = max(range(len(block_scores)), key=lambda i:block_scores[i][1])
        block, score = block_scores[idx]
        if not score:
            logger.warning(f'no block selected for {token}')
            unassigned.append(token)
        else:
            block_tokens[idx].append(token)
    return block_tokens, unassigned


def convert_pdf(fn):
    logger.info(f'analyzing {fn} using pdfplumber ...')
    page_data = preprocess_with_pdfplumber(fn)
    document = PawlsDocument.from_json(page_data)
    logger.info(f'processed {fn} into {len(document.pages)} pages')
    
    logger.info(f'converting {fn} into images ...')
    images = pdf2image.convert_from_path(fn)
    logger.info(f'converted {fn} into {len(images)} images')

    assert len(document.pages) == len(images), 'page number mismatch'

    return document, images


def scale_layout(layout, image, page):
    # rescale image coordinates to PDF coordinates
    width_ratio = page.width/image.size[0]
    height_ratio = page.height/image.size[1]
    if not 0.999 < width_ratio/height_ratio < 1.001:
        logger.warning(f'different w/h ratios: {width_ratio/height_ratio}')
    scaled_layout = [
        block.scale((width_ratio, height_ratio))
        for block in layout
    ]
    return scaled_layout


def predict_annotations(model, image, page):
    layout = model.detect(np.array(image))
    scaled_layout = scale_layout(layout, image, page)
    annotations = []
    for block in scaled_layout:
        annotation = Annotation(
            block.type, 
            BBox.from_layoutparser_block(block, page.height),
            page
        )
        annotations.append(annotation)
    return annotations


def annotate_to_pdf(infn, outfn, model, args):
    document, images = convert_pdf(infn)

    in_pdf = PdfFileReader(open(infn, 'rb'))
    out_pdf = PdfFileWriter()
    for page_idx, (image, page, in_page) in enumerate(
            zip(images, document.pages, in_pdf.pages)):
        print(f'processing page {page_idx} ...', file=sys.stderr, flush=True)
        annotations = predict_annotations(model, image, page)
        if annotations:
            ann_pdf = render_annotations(annotations)
            ann_page = ann_pdf.getPage(0)
            in_page.mergePage(ann_page)
        out_pdf.addPage(in_page)
    with open(outfn, 'wb') as output:
        out_pdf.write(output)


def annotate_to_xml(infn, outfn, model, args):
    document, images = convert_pdf(infn)

    with open(outfn, 'w') as out:
        print('<document>', file=out)
        for i, (image, page) in enumerate(zip(images, document.pages), start=1):
            print(f'  <page index="{page.index}">', file=out)
            logger.info(f'predicting for image {i}/{len(images)} ...')
            layout = model.detect(np.array(image))
            scaled_layout = scale_layout(layout, image, page)

            # use predicted layout to label tokens
            block_tokens, unassigned = assign_tokens_to_blocks(
                page, scaled_layout)

            assert len(layout) == len(block_tokens)
            for block, tokens in zip(scaled_layout, block_tokens):
                bbox = BBox.from_layoutparser_block(block, page.height)
                print(f'    <annotation>', file=out)
                print(block, file=out)    # TODO XML
                for token in tokens:                
                    print(token, file=out)    # TODO XML
                print(f'    </annotation>', file=out)
            print('  </page>', file=out)
        print('</document>', file=out)


def annotate_to_coco(infn, outfn, model, args):
    document, images = convert_pdf(infn)

    paper_id = 0
    coco = {
        'annotations': [],
        'categories': COCO_CATEGORIES,
        'images': [],
        'papers': [
            {
                'id': paper_id,
                'pages': len(document.pages),
                'paper_sha': file_sha256(infn),
            }
        ],
    }
    next_ann_id = 0
    for i, (image, page) in enumerate(zip(images, document.pages)):
        page_id = i
        coco['images'].append({
            'id': page_id,
            'page_number': i,
            'paper_id': paper_id,
            'width': page.width,
            'height': page.height,
        })

        annotations = predict_annotations(model, image, page)

        for a in annotations:
            coco['annotations'].append({
                'id': next_ann_id,
                'image_id': page_id,
                'category_id': a.coco_category_id(),
                'bbox': a.bbox.to_coco(page.height),
                'area': a.bbox.area,
                'iscrowd': False,
            })
            next_ann_id += 1

    with open(outfn, 'w') as out:
        json.dump(coco, out, indent=2)


def annotate(infn, outfn, model, args):
    if args.format == 'pdf':
        annotate_to_pdf(infn, outfn, model, args)
    elif args.format == 'xml':
        annotate_to_xml(infn, outfn, model, args)
    elif args.format == 'coco':
        annotate_to_coco(infn, outfn, model, args)
    else:
        raise NotImplementedError(f'format {args.format}')


def main(argv):
    args = argparser().parse_args(argv[1:])

    if args.verbose:
        logger.setLevel(logging.INFO)

    if args.labels is None:
        labels = DEFAULT_LABELS
    else:
        with open(args.labels) as f:
            labels = json.load(f)
    
    model = layoutparser.Detectron2LayoutModel(
        args.config,
        args.model,
        extra_config=["MODEL.ROI_HEADS.SCORE_THRESH_TEST", args.threshold],
        label_map=labels,
    )

    annotate(args.input, args.output, model, args)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
