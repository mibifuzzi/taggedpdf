# PDF structure element attribute. Reference: PDF 32000-1:2008:
# https://www.adobe.com/content/dam/acom/en/devnet/pdf/pdfs/PDF32000_2008.pdf.

from pikepdf import Name, Array

from .utils import clean_xml_attr


class Attribute:
    """Structure element attribute object."""
    def __init__(self, name, value, owner):
        # See 14.7.5 "Structure Attributes"
        self.name = name
        self.value = value
        self.owner = owner

    def struct_tree_str(self):
        return f'{self.name} {format_value_for_struct(self.value)}'

    def xml_tree_str(self):
        name = str(self.name)[1:]
        return f'{name}={clean_xml_attr(format_value_for_xml(self.value))}'

    def __str__(self):
        return f'{self.name}="{format_value_for_str(self.value)}"'


def format_value_for_xml(value):
    if isinstance(value, Name):
        string = str(value)[1:]
    elif isinstance(value, Array):
        string = ','.join(format_value_for_xml(i) for i in value)
    else:
        string = str(value)
    return string


def format_value_for_struct(value):
    # Attempting to match format with `pdfinfo -struct`
    if isinstance(value, Array):
        return '[' + ' '.join(format_value_for_struct(i) for i in value) + ']'
    elif isinstance(value, Decimal):
        valuestr = str(value)
        if valuestr.endswith('.0'):
            valuestr = valuestr[:-2]
        return valuestr
    else:
        try:
            return str(value)
        except:
            return repr(value)


def format_value_for_str(self, value):
    if isinstance(value, Array):
        return '[' + ' '.join(self.format_value_for_str(i) for i in value) + ']'
    else:
        try:
            return str(value)
        except:
            return repr(value)
