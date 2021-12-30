import sys

import unicodedata
import xml.etree.ElementTree as ET

from xml.sax.saxutils import escape, quoteattr


def pairs(iterable):
    # pairs('ABCDEFG') --> AB CD EF
    i = iter(iterable)
    return zip(i, i)


def remove_nonprintable(string):
    if remove_nonprintable.table is None:
        # keep newlines, tabs, and soft hyphens
        keep_exceptions = { '\n', '\t', '\u00AD' }
        # remove null
        remove_exceptions = { '\x00' }
        nonprintable = [
            chr(c) for c in range(sys.maxunicode) if
            (not chr(c).isprintable() or chr(c) in remove_exceptions)
            and chr(c) not in keep_exceptions
        ]
        remove_nonprintable.table = str.maketrans('', '', ''.join(nonprintable))
    return string.translate(remove_nonprintable.table)
remove_nonprintable.table = None


def clean_xml_text(string):
    return escape(remove_nonprintable(string))


def clean_xml_attr(value):
    return quoteattr(remove_nonprintable(str(value)))


def check_xml(string):
    try:
        root = ET.fromstring(string)
    except ET.ParseError as e:
        logger.error('output is not valid XML')
        # following https://stackoverflow.com/a/27779811
        line_num, column = e.position
        lines = string.splitlines()
        line = lines[line_num-1]
        mark = '{:->{}} HERE'.format('^', column)
        e.msg = '{}\n{}\n{}'.format(e, line, mark)
        raise
    return True

