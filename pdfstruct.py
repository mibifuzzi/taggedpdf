#!/usr/bin/env python3

# Output logical structure of tagged PDF files. Follows in part the
# implementation of `pdfinfo -struct` from poppler-utils.

import sys

from io import StringIO
from argparse import ArgumentParser

from taggedpdf import TaggedPdf, OutputFormat
from taggedpdf.utils import check_xml
from taggedpdf.logger import logger


def argparser():
    ap = ArgumentParser()
    formats = [f.value for f in OutputFormat]
    ap.add_argument('pdf', nargs='+')
    ap.add_argument(
        '--format',
        choices=formats,
        default=formats[0],
        help='output format'
    )
    ap.add_argument(
        '--skip-check',
        default=False,
        action='store_true',
        help='do not check that output is valid XML (with XML format)'
    )
    return ap


def output_pdf_struct(fn, args):
    pdf = TaggedPdf(fn)
    if pdf.struct_tree_root is None:
        logger.info(f'{fn}: no structure tree')
        return
    root = pdf.struct_tree_root

    if args.skip_check or args.format != 'xml':
        root.write_struct_tree(fmt=OutputFormat(args.format))
    else:
        assert args.format == 'xml'
        output = StringIO()
        root.write_struct_tree(fmt=OutputFormat(args.format), out=output)
        output = output.getvalue()
        check_xml(output)
        print(output, end='')


def main(argv):
    args = argparser().parse_args(argv[1:])

    for fn in args.pdf:
        try:
            output_pdf_struct(fn, args)
        except Exception as e:
            logger.error(f'{fn}: {e}')
            raise


if __name__ == '__main__':
    sys.exit(main(sys.argv))
