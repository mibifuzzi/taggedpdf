# Support functions for working with PDFMiner LTItems

from pdfminer.layout import LTChar, LTPage, LTFigure, LTRect, LTImage
from pdfminer.utils import bbox2str

from taggedpdf.utils import clean_xml_attr, clean_xml_text


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
    elif isinstance(item, LTRect):
        return (
            f'<rect'
            f' bbox="{bbox2str(item.bbox)}"'
            f' linewidth="{item.linewidth}"'
            f'/>'
        )
    elif isinstance(item, LTFigure):
        return (
            f'<figure'
            f' bbox="{bbox2str(item.bbox)}"'
            f'/>'
        )
    elif isinstance(item, LTImage):
        return (
            f'<image'
            f' name="{item.name}"'
            f' bbox="{bbox2str(item.bbox)}"'
            f' width="{item.srcsize[0]}"'
            f' height="{item.srcsize[1]}"'
            f'/>'
        )
    else:
        raise NotImplementedError(f'{type(item).__name__}')

