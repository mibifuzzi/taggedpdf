# COCO evaluation using pycocotools

import sys
import os
import io

from argparse import ArgumentParser
from contextlib import redirect_stdout, redirect_stderr

from pycocotools.coco import COCO
from pycocotools.cocoeval import COCOeval


def argparser():
    ap = ArgumentParser()
    ap.add_argument('--verbose', default=False, action='store_true')
    ap.add_argument('gold')
    ap.add_argument('pred')
    return ap


def assure_anns_have_scores(coco_data, score=1.0):
    for id_, ann in coco_data.anns.items():
        if 'score' not in ann:
            ann['score'] = score


def main(argv):
    args = argparser().parse_args(argv[1:])
    
    gold = COCO(args.gold)
    pred = COCO(args.pred)
    
    name = os.path.splitext(os.path.basename(args.gold))[0]

    assure_anns_have_scores(pred)
    
    evaluator = COCOeval(gold, pred, iouType='bbox')
    #evaluator.recThrs = TODO
    
    evaluator.evaluate()     # run per image evaluation
    evaluator.accumulate()   # accumulate per image results
    evaluator.summarize()    # display summary metrics of results

    print('Per-page results:')
    for i in gold.getImgIds():
        evaluator = COCOeval(gold, pred, iouType='bbox')
        evaluator.params.imgIds  = [i]
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            evaluator.evaluate()
            evaluator.accumulate()
            evaluator.summarize()
        avg_prec = evaluator.stats[0] # AP @ IoU=0.50:0.95 area=all maxDets=100
        avg_rec = evaluator.stats[8] # AR @ IoU=0.50:0.95 area=all maxDets=100
        if args.verbose:
            print(f'{name} page ', end='')
        print(f'{i}: AP:{avg_prec:.1%} AR:{avg_rec:.1%}')


if __name__ == '__main__':
    sys.exit(main(sys.argv))
