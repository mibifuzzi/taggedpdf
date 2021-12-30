# PDF structure type information. References are to PDF 32000-1:2008:
# https://www.adobe.com/content/dam/acom/en/devnet/pdf/pdfs/PDF32000_2008.pdf.

from enum import Enum

from pikepdf import Name


# From Table 333 "Standard structure types for grouping elements"
GROUPING_ELEMENT_TYPES = {
    Name.Document,
    Name.Part,
    Name.Art,
    Name.Sect,
    Name.Div,
    Name.BlockQuote,
    Name.Caption,
    Name.TOC,
    Name.TOCI,
    Name.Index,
    Name.NonStruct,
    Name.Private
}


# From Table 334 "Block-level structure elements"
BLOCK_LEVEL_ELEMENT_TYPES = {
    # Paragraphlike elements
    Name.P,
    Name.H,
    Name.H1,
    Name.H2,
    Name.H3,
    Name.H4,
    Name.H5,
    Name.H6,
    # List elements
    Name.L,
    Name.LI,
    Name.Lbl,
    Name.LBody,
    # Table element
    Name.Table
}


# From Table 337 "Standard structure types for table elements"
TABLE_ELEMENT_TYPES = {
    Name.TR,
    Name.TH,
    Name.TD,
    Name.THead,
    Name.TBody,
    Name.TFoot,
}


# From Table 338 "Standard structure types for inline-level structure elements"
INLINE_ELEMENT_TYPES = {
    Name.Span,
    Name.Quote,
    Name.Note,
    Name.Reference,
    Name.BibEntry,
    Name.Code,
    Name.Link,
    Name.Annot,
    Name.Ruby,
    Name.Warichu,
}


# From Table 339 –  Standard structure types for Ruby and Warichu elements
RUBY_AND_WARICHU_ELEMENT_TYPES = {
    Name.RB,
    Name.RT,
    Name.RP,
    Name.WT,
    Name.WP,
}


# From Table 340 "Standard structure types for illustration elements"
ILLUSTRATION_ELEMENT_TYPES = {
    Name.Figure,
    Name.Formula,
    Name.Form,
}


STANDARD_STRUCTURE_TYPES = (
    GROUPING_ELEMENT_TYPES |
    BLOCK_LEVEL_ELEMENT_TYPES |
    TABLE_ELEMENT_TYPES |
    INLINE_ELEMENT_TYPES |
    RUBY_AND_WARICHU_ELEMENT_TYPES |
    ILLUSTRATION_ELEMENT_TYPES
)


class ElementType(Enum):
    Undefined = 'undefined'
    Grouping = 'grouping'
    Inline = 'inline'
    Block = 'block'


STRUCT_TYPE_CATEGORY_MAP = {
    type_: category for types, category in (
        (GROUPING_ELEMENT_TYPES, ElementType.Grouping),
        (BLOCK_LEVEL_ELEMENT_TYPES, ElementType.Block),
        (INLINE_ELEMENT_TYPES, ElementType.Inline),
    )
    for type_ in types
}


def is_standard_type(type_):
    return type_ in STANDARD_STRUCTURE_TYPES


def struct_type_category(type_):
    return STRUCT_TYPE_CATEGORY_MAP.get(type_, ElementType.Undefined)
