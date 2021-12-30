# PDF structure tree objects. Reference: PDF 32000-1:2008:
# https://www.adobe.com/content/dam/acom/en/devnet/pdf/pdfs/PDF32000_2008.pdf.

import sys

from taggedpdf import parsing

from pikepdf import Dictionary, Array, Name

from .attribute import Attribute
from .structtype import ElementType, is_standard_type, struct_type_category
from .treedict import NameTree, NumberTree
from .utils import clean_xml_attr
from .cli import OutputFormat
from .logger import logger


class StructTreeRoot:
    """Root of tree representing document logical structure."""
    def __init__(self, root: Dictionary):
        self.root = root
        self.children = []    # StructElem objects
        self.element_map = {}    # StructElem object by obj-gen number

        # See 14.7.2 "Structure Hierarchy" and Table 322 "Entries in
        # the structure tree root" in Reference. Intentionally
        # skipping ParentTreeNextKey here.
        self.kids = self.root.get(Name.K)
        self.id_tree = parsing.get_dictionary(root, Name.IDTree)
        self.parent_tree = parsing.get_dictionary(root, Name.ParentTree)
        self.role_map = parsing.get_dictionary(root, Name.RoleMap)
        self.class_map = parsing.get_dictionary(root, Name.ClassMap)

        # Instantiate optional objects
        if self.id_tree is not None:
            self.id_tree = NameTree(self.id_tree)
        if self.parent_tree is not None:
            self.parent_tree = NumberTree(self.parent_tree)
        if self.role_map is not None:
            self.role_map = RoleMap(self.role_map)
        if self.class_map is not None:
            self.class_map = ClassMap(self.class_map)

        # Kids "may be either a dictionary representing a single
        # structure element or an array of such dictionaries."
        if isinstance(self.kids, Dictionary):
            self.children.append(StructElem(self.kids, self, None))
        elif isinstance(self.kids, Array):
            for i, kid in enumerate(self.kids):
                if not isinstance(kid, Dictionary):
                    raise ValueError(
                        '{Name.StructTreeRoot}{Name.K}[{i}] has wrong type'
                    )
                self.children.append(StructElem(kid, self, None))
        elif self.kids is not None:
            raise ValueError('{Name.StructTreeRoot}{Name.K} has wrong type')

    def add_element(self, objgen, element):
        assert objgen not in self.element_map
        self.element_map[objgen] = element

    def get_element(self, objgen):
        return self.element_map.get(objgen)

    def nodes(self):
        for child in self.children:
            yield from child.nodes()

    def write_struct_tree(self, fmt=OutputFormat.pdfinfo, out=sys.stdout):
        indent = 0 if fmt != OutputFormat.xml else 1
        if fmt == OutputFormat.xml:
            print('<document>', file=out)
        for child in self.children:
            child.write_struct_tree(fmt, indent, out)
        if fmt == OutputFormat.xml:
            print('</document>', file=out)


class StructElemBase:
    """Base class for structure tree node classes."""
    def __init__(self, root: StructTreeRoot, parent):
        self.root = root
        self.parent = parent
        self.attributes = []
        self.children = []
        self._content_by_page = {}
        self._pages = set()
        self.struct_type = None
        self.mcid = None
        self._bbox_cache = None

    def bbox(self, page):
        self._update_bbox_cache()
        return self._bbox_cache.get(page, None)

    def _update_bbox_cache(self):
        if self._bbox_cache is not None:
            return    # still valid
        else:
            self._bbox_cache = {}

        # only consider pages where some subtree element appears
        pages = sorted(self._pages)

        # bboxes given in attributes are not page-specific
        attr_bboxes = [
            BBox.from_pikepdf_attribute(a) for a in self.attributes
            if a.name == Name.BBox
        ]

        if attr_bboxes and len(pages) != 1:
            print(pages)
            self.write_struct_tree(fmt=OutputFormat.pdfinfo)
            logger.error('cannot resolve page for /BBox, removing')
            attr_bboxes = []

        def is_space_text_item(item):    # TODO find sensible place for this
            try:
                text = item.get_text()
            except:
                return False
            return text.isspace()

        for page in pages:
            # take union of bboxes of content items, nodes in the
            # subtree, and bbox attributes in the current element
            content_bboxes = [
                BBox(*item.bbox)
                for item in self._content_by_page.get(page, [])
                if not is_space_text_item(item)
            ]
            subtree_bboxes = [
                node.bbox(page) for node in self.nodes(include_self=False)
                if node.bbox(page) is not None
            ]
            self._bbox_cache[page] = BBox.union(
                content_bboxes + subtree_bboxes + attr_bboxes
            )

    def bboxes(self, include_space=False):
        return [self.bbox(i) for i in self._pages]

    def _invalidate_bbox_cache(self):
        if self._bbox_cache is not None:
            # had a previously calculated bbox, clear and propagate
            self._bbox_cache = None
            if self.parent is not None:
                self.parent._invalidate_bbox_cache()

    def _add_page(self, page):
        if page not in self._pages:
            # new page for this node, may also be new for ancestors
            self._pages.add(page)
            if self.parent is not None:
                self.parent._add_page(page)

    def add_content_item(self, page, item):
        self._add_page(page)
        if page not in self._content_by_page:
            self._content_by_page[page] = []
        self._content_by_page[page].append(item)
        self._invalidate_bbox_cache()

    def is_block(self):
        return struct_type_category(self.struct_type) == ElementType.Block

    def is_inline(self):
        return struct_type_category(self.struct_type) == ElementType.Inline

    def is_grouping(self):
        return struct_type_category(self.struct_type) == ElementType.Grouping

    def get_id(self):
        return None

    def is_content(self):
        raise NotImplementedError

    def is_objref(self):
        raise NotImplementedError

    def write_struct_tree(self, fmt, indent=0, out=sys.stdout):
        raise NotImplementedError

    def print_indent(self, indent, out):
        print('  '*indent, end='', file=out)

    def nodes(self, include_self=True):
        if include_self:
            yield self
        for child in self.children:
            yield from child.nodes()

    def add_child(self, element):
        try:
            self.children.append(self.parse_child(element))
        except ValueError as e:
            logger.warning(f'skip StructElem with error: {e}')

    def parse_child(self, element):
        # Kids can be dictionaries for another structure element,
        # integer MCID or marked-content reference dictionary denoting
        # a marked-content sequence, or object reference dictionary
        # denoting a PDF object.
        if isinstance(element, Dictionary):
            # If the value of K is a dictionary containing no Type entry,
            # it shall be assumed to be a structure element dictionary.
            # For a marked-content reference or a object reference dictionary
            # Type is required and shall be MCR or OBJR (resp.).
            if (Name.Type not in element or
                element[Name.Type] == Name.StructElem):
                return StructElem(element, self.root, self)
            elif element[Name.Type] == Name.MCR:
                return MCRefStructElem(element, self.root, self)
            elif element[Name.Type] == Name.OBJR:
                return ObjRefStructElem(element, self.root, self)
            else:
                raise ValueError(
                    f'StructElem child has wrong type {element[Name.Type]}')
        elif isinstance(element, int):
            return MCIDStructElem(element, self.root, self)
        else:
            raise NotImplementedError(f'{type(element)}, {repr(element)}')


class StructElem(StructElemBase):
    """Structure tree node."""
    def __init__(self, dictionary: Dictionary, root: StructTreeRoot, parent):
        super().__init__(root, parent)
        self.dictionary = dictionary
        root.add_element(dictionary.objgen, self)

        # Following Table 323 "Entries in a structure element dictionary"
        # Type is optional but must be "StructElem" if present
        self.type = dictionary.get(Name.Type)
        if self.type is not None and self.type != Name.StructElem:
            raise ValueError(
                f'StructElem Type has wrong value {self.type}')

        # Structure type (S) is a required name
        self.struct_type = parsing.get_name(dictionary, Name.S, required=True)

        # Structure type may be resolved to a standard type via the
        # RoleMap. Store original for reference.
        self.original_struct_type = self.struct_type
        if (self.root.role_map is not None and
            self.root.role_map.get(self.struct_type) is not None):
            self.struct_type = self.root.role_map.get(self.struct_type)

        # Empty structure types ("/") seem to appear in some documents.
        # Poppler refuses to create these, fo follow suite.
        # (TODO: also check for conformance for other types.)
        if self.struct_type == '/':
            raise ValueError(f'wrong type "{self.struct_type}"')

        # Parent (P) is a required indirect reference to a dictionary,
        # but arrays appear in some PDFs. Poppler StructElement.cc
        # also only checks for a reference. Implemented loosely here.
        self.parent_ref = dictionary.get(Name.P)
        if self.parent_ref is None:
            raise ValueError(f'missing {Name.P} for StructElem')
        if not self.parent_ref.is_indirect:
            raise ValueError(f'StructElem {Name.P} is not indirect')

        # Kids is optional and may have various types, including an
        # array of those types.
        self.kids = dictionary.get(Name.K)
        if isinstance(self.kids, Array):
            for i, kid in enumerate(self.kids):
                self.add_child(kid)
        elif self.kids is not None:
            self.add_child(self.kids)

        # Attributes (A) is optional and can be either an dictionary,
        # a stream, or an array.
        self.attributes = parsing.parse_attributes(dictionary.get(Name.A))

        # Attribute class (C) is optional and can be a name or an array of
        # names
        self.attrib_classes = parsing.parse_attrib_class(dictionary.get(Name.C))

        # Attribute classes are used to update attributes without
        # overwriting directly attached values
        for attrib_class in self.attrib_classes:
            self.attributes = self.root.class_map.apply_mapping(
                self.attributes, attrib_class)

        # The remaining are optional integer or string values.
        self.id = parsing.get_string(dictionary, Name.ID)
        self.revision = parsing.get_integer(dictionary, Name.R)
        self.title = parsing.get_string(dictionary, Name.T)
        self.lang = parsing.get_string(dictionary, Name.Lang)
        self.alt = parsing.get_string(dictionary, Name.Alt)
        self.expanded = parsing.get_string(dictionary, Name.E)
        self.actual_text = parsing.get_string(dictionary, Name.ActualText)

    def get_content(self):
        return [
            item for page, items in sorted(self._content_by_page.items())
            for item in items
        ]

    def get_content_text(self):
        text = []
        for item in self.get_content():
            try:
                text.append(item.get_text())
            except:
                # this is expected to fail for non-text layout items
                logger.info(f'failed get_text() for {item}')
        return ''.join(text)

    def get_nontext_content(self):
        items = []
        for item in self.get_content():
            try:
                item.get_text()
            except:
                items.append(item)
        return items

    def get_id(self):
        return self.id

    def is_content(self):
        return False

    def is_objref(self):
        return False

    def write_struct_tree_pdfinfo(self, fmt, indent=0, out=sys.stdout):
        self.print_indent(indent, out)

        write = lambda s: print(s, end='', file=out)
        write(str(self.struct_type)[1:])
        if self.id is not None:
            write(f' <{self.id}>')
        if self.title is not None:
            write(f' "{self.title}"')
        if self.is_inline() or self.is_block():
            write(' (block)' if self.is_block() else ' (inline)')
        if self.attributes:
            write(':\n')
            for attrib in self.attributes:
                self.print_indent(indent+1, out)
                write(f' {attrib.struct_tree_str()}\n')
        else:
            write('\n')
        if self.get_content():
            self.print_indent(indent+1, out)
            write(f'"{self.get_content_text()}"\n')

        for child in self.children:
            child.write_struct_tree(fmt, indent+1, out)

    def deduplicated_attributes(self):
        # PDF can have multiple attributes with the same name, but
        # some output formats such as XML cannot. As duplicates are rare,
        # drop all but the first and warn.
        filtered, seen = [], set()
        for a in self.attributes:
            if str(a.name) not in seen:
                filtered.append(a)
                seen.add(str(a.name))
            else:
                logger.warning(
                    f'dropping redundant {a.name} attribute for XML output')
        return filtered

    def write_struct_tree_xml(self, fmt, indent=0, out=sys.stdout):
        self.print_indent(indent, out)
        type_ = str(self.struct_type)[1:]
        pages = ','.join(str(p) for p in self._pages) if self._pages else ''
        cat = struct_type_category(self.struct_type)
        attributes = self.deduplicated_attributes()
        print(
            ''.join([
                f'<{type_}',
                f' pages="{pages}"',
                (f' title={clean_xml_attr(str(self.title))}'
                 if self.title is not None else ''),
                (f' category={clean_xml_attr(str(cat.value))}'
                 if cat is not None else ''),
                f''.join(f' {a.xml_tree_str()}' for a in attributes),
                f'>'
            ]),
            file=out
        )
        if self.get_content_text():
            self.print_indent(indent+1, out)
            text = self.get_content_text()
            print(f'<content text={clean_xml_attr(text)}/>', file=out)
        for child in self.children:
            child.write_struct_tree(fmt, indent+1, out)
        self.print_indent(indent, out)
        print(f'</{type_}>', file=out)

    def write_struct_tree(self, fmt, indent=0, out=sys.stdout):
        if fmt == OutputFormat.pdfinfo:
            return self.write_struct_tree_pdfinfo(fmt, indent, out)
        elif fmt == OutputFormat.xml:
            return self.write_struct_tree_xml(fmt, indent, out)
        else:
            raise NotImplementedError

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        attrs = ''.join(f' {a}' for a in self.attributes)
        return (
            f'StructElem('
            f'type={self.struct_type}'
            f' pages={sorted(self._content_by_page.keys())}'
            f' bbox={self.bboxes()}'
            f'{attrs})'
        )


class MCIDStructElem(StructElemBase):
    """Marked-content identifier structure tree leaf."""
    def __init__(self, mcid, root: StructTreeRoot, parent):
        super().__init__(root, parent)
        self.struct_type = 'MCID'
        self.mcid = mcid

    def is_content(self):
        return True

    def is_objref(self):
        return False

    def write_struct_tree(self, fmt, indent=0, out=sys.stdout):
        if fmt == OutputFormat.pdfinfo:
            pass    # not included in `pdfinfo -struct` output
        elif fmt == OutputFormat.xml:
            self.print_indent(indent, out)
            print(
                ''.join([
                    f'<MCID',
                    f' mcid="{self.mcid}"',
                    f'/>']),
                file=out
            )
        else:
            raise NotImplementedError

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return f'MCID({self.mcid})'


class MCRefStructElem(StructElemBase):
    """Marked-content reference structure tree leaf."""
    def __init__(self, dictionary: Dictionary, root: StructTreeRoot, parent):
        super().__init__(root, parent)
        self.dictionary = dictionary

        # See Reference Table 324 "Entries in a marked-content
        # reference dictionary"
        assert dictionary[Name.Type] == Name.MCR
        self.struct_type = dictionary[Name.Type]
        self.mcid = parsing.get_integer(dictionary, Name.MCID, required=True)

        # TODO check types here, handle optional StmOwn
        self.page = parsing.get_dictionary(dictionary, Name.Pg)
        self.stream = dictionary.get(Name.Stm)

    def is_content(self):
        return True

    def is_objref(self):
        return False

    def write_struct_tree(self, fmt, indent=0, out=sys.stdout):
        if fmt == OutputFormat.pdfinfo:
            pass    # not included in `pdfinfo -struct` output
        elif fmt == OutputFormat.xml:
            self.print_indent(indent, out)
            type_ = str(self.struct_type)[1:]
            print(
                ''.join([
                    f'<{type_}',
                    f' mcid="{self.mcid}"',
                    f'/>']),
                file=out
            )
        else:
            raise NotImplementedError


class ObjRefStructElem(StructElemBase):
    """Object reference structure tree leaf."""
    def __init__(self, dictionary: Dictionary, root: StructTreeRoot, parent):
        super().__init__(root, parent)
        self.dictionary = dictionary

        # See Reference Table 325 "Entries in an object reference dictionary"
        assert dictionary[Name.Type] == Name.OBJR
        self.struct_type = dictionary[Name.Type]
        self.obj = parsing.get_dictionary(dictionary, Name.Obj, required=True)
        self.page = dictionary.get(Name.Pg)    # TODO check type, is_indirect

    def is_content(self):
        return True

    def is_objref(self):
        return True

    def write_struct_tree(self, fmt, indent=0, out=sys.stdout):
        obj_num, gen_num = self.obj.objgen
        if fmt == OutputFormat.pdfinfo:
            self.print_indent(indent, out)
            print('Object', obj_num, gen_num, file=out)
        elif fmt == OutputFormat.xml:
            self.print_indent(indent, out)
            print(f'<Object num="{obj_num}" gen="{gen_num}"/>', file=out)
        else:
            raise NotImplementedError


class ClassMap:
    """Map from attribute class names to attribute objects in structure tree."""
    def __init__(self, dictionary: Dictionary):
        self.dictionary = dictionary

        self.mapping = {}
        for key, value in dictionary.items():
            self.mapping[str(key)] = parsing.parse_attributes(value)

    def apply_mapping(self, attributes, attrib_class):
        if attributes is None:
            attributes = []
        if str(attrib_class) not in self.mapping:
            raise ValueError(f'missing attribute class {attrib_class}')
        for attribute in self.mapping[str(attrib_class)]:
            if any(a.name == attribute.name for a in attributes):
                logger.debug(f'not overwriting {attribute.name}')
            else:
                attributes.append(attribute)
        return attributes


class RoleMap:
    """Map from custom structure types to approximate standard equivalents."""
    def __init__(self, dictionary: Dictionary):
        self.dictionary = dictionary

        self.mapping = {}
        for key, value in dictionary.items():
            if isinstance(value, Name):
                self.mapping[str(key)] = value
            else:
                logger.warning(
                    f'unexpected type {value._type_name} in name mapping')

    def get(self, key, default=None):
        return self.mapping.get(str(key), default)
