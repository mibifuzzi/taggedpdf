#!/usr/bin/env python3

# Run pdf2image on given PDF and save images. This part of processing
# is separated here to support running predictions on systems without
# poppler.

import sys
import os

import pdf2image

from argparse import ArgumentParser


def argparser():
    ap = ArgumentParser()
    ap.add_argument('input', metavar='PDF')
    ap.add_argument('output', metavar='DIR')
    return ap


def main(argv):
    args = argparser().parse_args(argv[1:])

    if not os.path.isdir(args.output):
        print(f'error: not a directory: {args.output}')
        return 1
    
    images = pdf2image.convert_from_path(args.input)
    for i, image in enumerate(images):
        base = os.path.splitext(os.path.basename(args.input))[0]
        outfn = os.path.join(args.output, f'{base}-page{i:04}.png')
        image.save(outfn)


if __name__ == '__main__':
    sys.exit(main(sys.argv))
