# PDF name and number trees. Reference: PDF 32000-1:2008:
# https://www.adobe.com/content/dam/acom/en/devnet/pdf/pdfs/PDF32000_2008.pdf.

from collections import OrderedDict

from pikepdf import Dictionary, Name, String

from taggedpdf import parsing
from .utils import pairs
from .logger import logger


class NameOrNumberTreeNode:
    """Base class for NameTreeNode and NumberTreeNode."""
    def __init__(self, dictionary: Dictionary, root, value_key):
        assert value_key in (Name.Names, Name.Nums)
        self.dictionary = dictionary
        self.root = root
        self.is_root = root is self
        self.children = []

        # See 7.9.6 "Name Trees", 7.9.7 "Number Trees" and Tables 36
        # "Entries in a name tree node dictionary" and 37 "Entries in
        # a number tree node dictionary" in Reference
        self.kids = parsing.get_array(dictionary, Name.Kids)
        self.values = parsing.get_array(dictionary, value_key)
        self.limits = parsing.get_array(dictionary, Name.Limits)

        # Limits is required in intermediate and leaf nodes and
        # should not appear in the root node.
        if self.is_root and self.limits is not None:
            logger.error('tree root has Limits')
        elif self.limits is None and not self.is_root:
            logger.error('missing Limits for non-root tree node')

        # Either but not both of Kids and Names/Numbers is required
        if self.kids is None and self.values is None:
            logger.error(f'tree node has neither kids nor values')
        if self.kids is not None and self.values is not None:
            logger.error('tree node has both kids and values')

        if self.kids is not None:
            for i, kid in enumerate(self.kids):
                self.add_child(kid)
        if self.values is not None:
            if len(self.values) % 2:
                logger.warning(f'odd number of values: {len(self.values)}')
            for key, value in pairs(self.values):
                self.root[key] = value

    def add_child(self, element):
        try:
            self.children.append(self.parse_child(element))
        except Exception as e:
            logger.warning(f'skip tree node with error: {e}')

    def parse_key(self, key):
        raise NotImplementedError()

    def parse_child(self, element):
        raise NotImplementedError()

    def is_intermediate(self):
        return (
            self.kids is not None and
            self.names is None and
            not self.is_root
        )

    def is_leaf(self):
        return (
            self.kids is None and
            self.names is not None and
            not self.is_root
        )


class NameTreeNode(NameOrNumberTreeNode):
    """Node in tree-structured ordered dictionary with binary string keys."""
    def __init__(self, dictionary: Dictionary, root):
        super().__init__(dictionary, root, Name.Names)

    def parse_child(self, element):
        if not isinstance(element, Dictionary):
            raise ValueError('name tree node child is not dictionary')
        if not element.is_indirect:
            logger.warning('name tree node child is not indirect')
        return NameTreeNode(element, self.root)


class NameTree(NameTreeNode):
    """Tree-structured ordered dictionary with binary string keys."""
    def __init__(self, dictionary: Dictionary):
        self._dict = OrderedDict()
        super().__init__(dictionary, root=self)

    def __setitem__(self, key, value):
        assert isinstance(key, String)
        key = str(key)
        if key in self._dict:
            raise ValueError(f'duplicate key "{key}" in name tree')
        self._dict[key] = value

    def __getitem__(self, key):
        assert isinstance(key, (String, str))
        key = str(key)
        return self._dict[key]

    def __contains__(self, key):
        assert isinstance(key, (String, str))
        key = str(key)
        return key in self._dict


class NumberTreeNode(NameOrNumberTreeNode):
    """Node in tree-structured ordered dictionary with integer keys."""
    def __init__(self, dictionary: Dictionary, root):
        super().__init__(dictionary, root, Name.Nums)

    def parse_child(self, element):
        if not isinstance(element, Dictionary):
            raise ValueError('number tree node child is not dictionary')
        if not element.is_indirect:
            logger.warning('number tree node child is not indirect')
        return NumberTreeNode(element, self.root)


class NumberTree(NumberTreeNode):
    """Tree-structured ordered dictionary with integer keys."""
    def __init__(self, dictionary: Dictionary):
        self._dict = OrderedDict()
        super().__init__(dictionary, root=self)

    def __setitem__(self, key, value):
        assert isinstance(key, int)
        if key in self._dict:
            raise ValueError(f'duplicate key "{key}" in number tree')
        self._dict[key] = value

    def __getitem__(self, key):
        assert isinstance(key, int)
        return self._dict[key]

    def __contains__(self, key):
        assert isinstance(key, int)
        return key in self._dict
