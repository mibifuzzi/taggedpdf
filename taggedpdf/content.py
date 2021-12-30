# Support for content extraction for tagged PDFs

import sys

from collections import OrderedDict, defaultdict, namedtuple

from pdfminer.pdfpage import PDFPage
from pdfminer.converter import PDFLayoutAnalyzer
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.utils import bbox2str
from pdfminer.psparser import PSLiteral
from pdfminer.layout import (
    LTPage, LTChar, LTLine, LTCurve, LTRect, LTFigure, LTImage
)

from .utils import check_xml
from .logger import logger


def argparser():
    from argparse import ArgumentParser
    ap = ArgumentParser()
    ap.add_argument('pdf')
    return ap


TaggedContentItem = namedtuple('TaggedContentItem', 'tags item')


class ContentTag:
    def __init__(self, page, name, properties):
        self.page = page
        self.name = name
        self.properties = properties if properties is not None else {}

    @property
    def str_properties(self):
        return { k: self.str_value(v) for k, v in self.properties.items() }

    @property
    def mcid(self):
        try:
            return self.properties.get('MCID')
        except:
            logger.error(f'cannot get MCID from {self.name} properties:'
                         f' {self.properties}')
            return None

    def add_item(self, item):
        self.items.append(item)

    def __str__(self):
        props_str = ''.join(
            f' {k}={v}' for k, v in self.str_properties.items()
        )
        return f'ContentTag(name={self.name}{props_str})'

    def __repr__(self):
        return self.__str__()

    @staticmethod
    def str_value(value):
        if isinstance(value, PSLiteral):
            return value.name
        elif isinstance(value, bytes):
            try:
                return value.decode('ascii')    # TODO
            except:
                pass
        else:
            return str(value)


class TaggedContent:
    def __init__(self):
        self.content_by_page = defaultdict(list)
        self.items_by_page_and_mcid = defaultdict(lambda: defaultdict(list))

    def add_item(self, page, tags, item):
        for tag in tags:
            if tag.mcid is not None:
                self.items_by_page_and_mcid[page][tag.mcid].append(item)
        tagged_item = TaggedContentItem(tags[:], item)
        self.content_by_page[page].append(tagged_item)

    def output_xml(self, out=sys.stdout):
        self.output_xml_start_element(out, 'document')
        for page in sorted(self.content_by_page.keys()):
            self.output_xml_start_element(out, 'page', {'index': page}, depth=1)
            for tagged_item in self.content_by_page[page]:
                self.output_tagged_item_xml(out, tagged_item, depth=2)
            self.output_xml_end_element(out, 'page', depth=1)
        self.output_xml_end_element(out, 'document')

    def output_tagged_item_xml(self, out, tagged_item, depth):
        # following pdfminer.six converter.py XMLConverter
        pdf_tags, item = tagged_item.tags, tagged_item.item
        attrs, text = OrderedDict(), None
        if isinstance(item, LTChar):
            xml_tag = 'char'
            attrs['font'] = item.fontname
            attrs['colourspace'] = item.ncs.name
            attrs['ncolour'] = item.graphicstate.ncolor
            attrs['size'] = f'{item.size:.3f}'
            text = item.get_text()
        elif isinstance(item, LTLine):
            xml_tag = 'line'
            attrs['linewidth'] = item.linewidth
        elif isinstance(item, LTCurve):
            xml_tag = 'curve'
            attrs['linewidth'] = item.linewidth
        elif isinstance(item, LTRect):
            tag = 'rect'
            attrs['linewidth'] = item.linewidth
        elif isinstance(item, LTFigure):
            xml_tag = 'figure'
            attrs['name'] = item.name
        elif isinstance(item, LTImage):
            xml_tag = 'image'
            attrs['name'] = item.name
        else:
            raise NotImplementedError(type(item).__name__)

        # everything has a bbox
        attrs['bbox'] = bbox2str(item.bbox)

        # add pdf tag names and properties
        if pdf_tags:
            attrs['tag_names'] = ','.join(t.name for t in pdf_tags)
        for pdf_tag in pdf_tags:
            for k, v in pdf_tag.str_properties.items():
                key = f'tag_{k}'
                if key not in attrs:
                    attrs[key] = v
                else:
                    attrs[key] = f'{attrs[key]},{v}'
        self.output_xml_element(out, xml_tag, attrs, text, depth)


    @staticmethod
    def output_indent(out, depth):
        print('  '*depth, end='', file=out)

    @staticmethod
    def xml_tag_string(name, attrs=None, empty=False):
        if not attrs:
            attr_str = ''
        else:
            attr_str = ''.join(f' {k}="{str(v)}"' for k, v in attrs.items())
        if not empty:
            return f'<{name}{attr_str}>'
        else:
            return f'<{name}{attr_str}/>'

    @staticmethod
    def output_xml_start_element(out, name, attrs=None, depth=0):
        TaggedContent.output_indent(out, depth)
        print(TaggedContent.xml_tag_string(name, attrs), file=out)

    @staticmethod
    def output_xml_end_element(out, name, depth=0):
        TaggedContent.output_indent(out, depth)
        print(TaggedContent.xml_tag_string(f'/{name}'), file=out)

    @staticmethod
    def output_xml_element(out, name, attrs=None, text=None, depth=0):
        TaggedContent.output_indent(out, depth)
        if text is None:
            print(TaggedContent.xml_tag_string(name, attrs, empty=True),
                  file=out)
        else:
            print(''.join([
                TaggedContent.xml_tag_string(name, attrs),
                text,
                TaggedContent.xml_tag_string(f'/{name}'),
            ]), file=out)


class TaggedContentExtractor(PDFLayoutAnalyzer):
    def __init__(self, resource_manager):    #, pdf_struct):
        super().__init__(resource_manager)
        #self.pdf_struct = pdf_struct
        self.page_index = None
        self.current_page = None
        #self.current_struct_elem = None
        self._tag_stack = []
        self.extracted_content = TaggedContent()

    def begin_page(self, *args, **argv):
        super().begin_page(*args, **argv)
        if self.page_index is None:
            self.page_index = 0
        else:
            self.page_index += 1
        self.current_page = self.cur_item
        assert isinstance(self.current_page, LTPage)
        assert not self._tag_stack

    def end_page(self, *args, **argv):
        super().end_page(*args, **argv)
        self.current_page = None
        assert not self._tag_stack

    def begin_figure(self, *args, **argv):
        super().begin_figure(*args, **argv)
        figure = self.cur_item
        assert isinstance(figure, LTFigure)
        self.add_content_item(figure)

    def end_figure(self, *args, **argv):
        super().end_figure(*args, **argv)

    def paint_path(self, *args, **argv):
        super().paint_path(*args, **argv)
        item = self.cur_item._objs[-1]    # TODO there may be multiple
        self.add_content_item(item)

    def render_image(self, *args, **argv):
        super().render_image(*args, **argv)
        image = self.cur_item._objs[-1]
        assert isinstance(image, LTImage)
        self.add_content_item(image)

    def render_char(self, *args, **argv):
        value = super().render_char(*args, **argv)
        char = self.cur_item._objs[-1]
        assert isinstance(char, LTChar)
        self.add_content_item(char)
        return value

    def begin_tag(self, tag, props=None):
        # Called by PDFPageInterpreter for BMC and BDC
        # if not isinstance(props, dict) or 'MCID' not in props:
        #     return    # not marked content
        # mcid = props['MCID']
        #assert self.current_struct_elem is None
        #self.current_struct_elem = self.get_struct_elem(mcid)
        self._tag_stack.append(ContentTag(self.page_index, tag.name, props))
        # tags can nest, but MCIDs cannot
        assert sum(t.mcid is not None for t in self._tag_stack) < 2

    def end_tag(self):
        # Called by PDFPageInterpreter for EMC
        #self.current_struct_elem = None
        #self.current_tag = None
        self._tag_stack.pop()

    def add_content_item(self, item):
        type_name = type(item).__name__
        # if self.current_struct_elem is not None:
        #     self.current_struct_elem.add_content_item(self.page_index, item)
        #     self.struct_count[type_name] += 1
        # else:
        #     #print(f'non-struct: {item}', file=sys.stderr)
        #     self.non_struct_count[type_name] += 1
        self.extracted_content.add_item(self.page_index, self._tag_stack, item)

    # def get_struct_elem(self, mcid):
    #     # From 14.7.4.4 "Finding Structure Elements from Content
    #     # Items": Because a marked-content sequence is not an
    #     # object in its own right, its parent tree key shall be
    #     # found in the StructParents entry of the page object or
    #     # other content stream in which the sequence resides. The
    #     # value retrieved from the parent tree shall not be a
    #     # reference to the parent structure element itself but to
    #     # an array of such references—one for each marked-content
    #     # sequence contained within that content stream.  The
    #     # parent structure element for the given sequence shall be
    #     # found by using the sequence’s marked-content identifier
    #     # as an index into this array.
    #     page_idx = self.page_index
    #     parent_tree_idx = self.pdf_struct.page_struct_parents[page_idx]
    #     if parent_tree_idx is None:
    #         logger.warning(f'missing StructParents for page {page_idx}')
    #         return None
    #     struct_tree = self.pdf_struct.struct_tree_root
    #     parent_tree = struct_tree.parent_tree[parent_tree_idx]
    #     try:
    #         parent = parent_tree[mcid]
    #     except IndexError:
    #         logger.error(f'invalid reference {mcid} to parent tree of'
    #                      f' {len(parent_tree)} items')
    #         return None # raise
    #     # Grab our StructElem object using objgen lookup.
    #     struct_elem = struct_tree.get_element(parent.objgen)
    #     return struct_elem

    def stats(self):
        s, t = self.struct_char, self.total_char
        return f'{s/t:.1%} ({s}/{t}) of chars in struct'


def extract_content(pdf_path):
    resource_manager = PDFResourceManager()
    extractor = TaggedContentExtractor(resource_manager)
    interpreter = PDFPageInterpreter(resource_manager, extractor)
    with open(pdf_path, 'rb') as f:
        for page in PDFPage.get_pages(f):
            interpreter.process_page(page)
    return extractor.extracted_content


# def add_content(pdf_path, pdf_struct):
#     # process PDF with pdfminer and TaggedContentExtractor, providing
#     # the latter with the PdfStruct, through which layout items can be
#     # attached to the relevant parts of the structure tree.
#     resource_manager = PDFResourceManager()
#     extractor = TaggedContentExtractor(resource_manager, pdf_struct)
#     interpreter = PDFPageInterpreter(resource_manager, extractor)
#     with open(pdf_path, 'rb') as f:
#         for page in PDFPage.get_pages(f):
#             interpreter.process_page(page)


def main(argv):
    args = argparser().parse_args()

    content = extract_content(args.pdf)
    content.output_xml()


if __name__ == '__main__':
    sys.exit(main(sys.argv))
