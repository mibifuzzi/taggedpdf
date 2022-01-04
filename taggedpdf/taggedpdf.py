# Partial implementation of PDF structure analysis. Reference: PDF 32000-1:2008:
# https://www.adobe.com/content/dam/acom/en/devnet/pdf/pdfs/PDF32000_2008.pdf.
# Follows part of the implementation in poppler-utils.

from taggedpdf import parsing

from pikepdf import Pdf, Dictionary, Array, Name

from .structtree import StructTreeRoot
from .content import extract_content
from .bbox import BBox
from .logger import logger


class MarkInfo:
    def __init__(self, dictionary: Dictionary):
        self.dictionary = d = dictionary

        # See Reference Table 321 "Entries in the mark information
        # dictionary"
        self.marked = parsing.get_boolean(d, Name.Marked),
        self.suspects = parsing.get_boolean(d, Name.Suspects),
        self.user_properties = parsing.get_boolean(d, Name.UserProperties)


class TaggedPdf:
    def __init__(self, pdf_path, skip_content=False):
        self.pdf = Pdf.open(pdf_path)
        self.dictionary = d = self.pdf.Root
        self.nonmarked_by_page = None

        # See 7.7.2 "Document Catalog" and Table 28 "Entries in the
        # catalog dictionary" in Reference. Only parsed partially.
        self.version = parsing.get_name(d, Name.Version)
        self.struct_tree_root = parsing.get_dictionary(d, Name.StructTreeRoot)
        self.mark_info = parsing.get_dictionary(d, Name.MarkInfo)

        # Instantiate objects (TODO: make StructTreeRoot lazy?)
        if self.struct_tree_root is not None:
            self.struct_tree_root = StructTreeRoot(self.struct_tree_root)
        if self.mark_info is not None:
            self.mark_info = MarkInfo(self.mark_info)

        # To associate content items with structure elements, in
        # addition to information in page content it's necessary to
        # have access to the value of /StructParents for each page
        # (see 14.7.4.4, "Finding Structure Elements from Content Items")
        self.page_struct_parents = [
            page.get(Name.StructParents)
            for page in self.pdf.pages
        ]

        # Use the /StructParents information to idenfity which
        # pages structure elements appear on
        for page_idx, parent_tree_idx in enumerate(self.page_struct_parents):
            if parent_tree_idx is None:
                continue
            struct_tree = self.struct_tree_root
            parent_array = struct_tree.parent_tree[parent_tree_idx]
            assert isinstance(parent_array, Array)
            for parent in parent_array:
                if parent is None:
                    continue
                struct_elem = struct_tree.get_element(parent.objgen)
                if struct_elem is None:
                    continue
                struct_elem._add_page(page_idx)

        # Attach content items to structure elements (TODO: make lazy?)
        if not skip_content:
            extracted = extract_content(pdf_path)
            for page in extracted.items_by_page_and_mcid:
                for mcid in extracted.items_by_page_and_mcid[page]:
                    struct_elem = self.get_struct_elem(page, mcid)
                    if struct_elem is None:
                        continue    # TODO figure out why these can miss
                    for item in extracted.items_by_page_and_mcid[page][mcid]:
                        struct_elem.add_content_item(page, item, mcid)
            # also store content outside structure
            self.nonmarked_by_page = extracted.nonmarked_items_by_page

    @property
    def page_count(self):
        return len(self.pdf.pages)

    def get_struct_elem(self, page, mcid):
        # From 14.7.4.4 "Finding Structure Elements from Content
        # Items": Because a marked-content sequence is not an
        # object in its own right, its parent tree key shall be
        # found in the StructParents entry of the page object or
        # other content stream in which the sequence resides. The
        # value retrieved from the parent tree shall not be a
        # reference to the parent structure element itself but to
        # an array of such references—one for each marked-content
        # sequence contained within that content stream.  The
        # parent structure element for the given sequence shall be
        # found by using the sequence’s marked-content identifier
        # as an index into this array.
        try:
            parent_tree_idx = self.page_struct_parents[page]
        except:
            logger.error(f'failed to find parent tree index for {page}')
            raise
        if parent_tree_idx is None:
            logger.warning(f'StructParents for page {page} is None')
            return None
        struct_tree = self.struct_tree_root
        parent_tree = struct_tree.parent_tree[parent_tree_idx]
        try:
            parent = parent_tree[mcid]
        except IndexError:
            logger.error(f'invalid reference {mcid} to parent tree of'
                         f' {len(parent_tree)} items')
            return None # raise
        if parent is None:
            logger.warning('value in parent tree is None')
            return None
        # Grab StructElem object using objgen lookup.
        struct_elem = struct_tree.get_element(parent.objgen)
        return struct_elem

    def get_cropbox(self, page_index):
        return BBox.from_pikepdf_array(self.pdf.pages[page_index].cropbox)
