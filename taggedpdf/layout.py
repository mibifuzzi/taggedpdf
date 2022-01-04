# Layout analysis support

from pdfminer.layout import (
    LTChar, LTContainer, LTTextLine, LTTextLineHorizontal,
    LTLayoutContainer, LAParams
)

from taggedpdf.logger import logger


def _print_layout_hierarchy(item, containers_only=True, depth=0):
    # debugging
    if containers_only and not isinstance(item, LTContainer):
        return
    print('    '*depth, item)
    try:
        for i in item:
            _print_layout_hierarchy(i, containers_only, depth+1)
    except:
        pass


def _get_textlines(container: LTContainer):
    if isinstance(container, LTTextLine):
        yield container
    else:
        for item in container:
            if isinstance(item, LTContainer):
                yield from _get_textlines(item)


def get_textlines(container: LTContainer):
    return list(_get_textlines(container))


def relative_overlaps(span1, span2):
    """Return the length of the span overlap relative to the span lengths."""
    length1, length2 = span1[1]-span1[0], span2[1]-span2[0]
    assert length1 > 0 and length2 > 0
    overlap = (max(span1[0], span2[0]), min(span1[1], span2[1]))
    ovl_length = overlap[1]-overlap[0]
    if ovl_length < 0:
        return 0, 0    # no overlap
    else:
        return ovl_length/length1, ovl_length/length2


def _hierarchy_subset(item, target_items):
    # Yield subset of items in container hierarchy rooted at item that
    # are found in target_items
    try:
        if item in target_items:
            yield item
    except:
        pass
    try:
        for i in item:
            yield from _hierarchy_subset(i, target_items)
    except:
        pass


def group_into_lines(chars):
    same_line = lambda s1, s2: max(relative_overlaps(s1, s2)) >= 0.5

    lines, line_vspan = [], None
    for char in chars:
        char_vspan = (char.bbox[1], char.bbox[3])
        if lines and same_line(line_vspan, char_vspan):
            # TODO check that characters are in sensible order
            lines[-1].append(char)
            line_vspan = (min(line_vspan[0], char_vspan[0]),
                          max(line_vspan[1], char_vspan[1]))
        else:
            # new line
            lines.append([char])
            line_vspan = char_vspan
    return lines


def split_into_columns(layout_items, bbox):
    """Split layout items forming paragraph-like text into columns."""

    chars, others = [], []
    for i in layout_items:
        if isinstance(i, LTChar):
            chars.append(i)
        else:
            others.append(i)

    same_column = lambda s1, s2: max(relative_overlaps(s1, s2)) >= 0.5

    columns, col_hspan = [], None
    for textline in group_into_lines(chars):
        line_hspan = (textline[0].bbox[0], textline[-1].bbox[2])
        if columns and same_column(col_hspan, line_hspan):
            columns[-1].append(textline)
            col_hspan = (min(col_hspan[0], line_hspan[0]),
                         max(col_hspan[1], line_hspan[1]))
        else:
            # new column
            columns.append([textline])
            col_hspan = line_hspan

    # If there are not multiple columns, just return a single "column"
    # with the original items to avoiding issues with not being able
    # to organize non-text items into columns.
    if len(columns) < 2:
        return [layout_items]

    # Filter columns back to the original layout_items (TODO: no longer
    # necessary as we're not using LTLayoutContainer.analyze())
    original_set = set(layout_items)
    column_items = [list(_hierarchy_subset(c, original_set)) for c in columns]

    # Some non-text items may have been lost; warn
    col_sets = [set(c) for c in column_items]
    col_union = set().union(*col_sets)
    if col_union != original_set:
        for i in original_set - col_union:
            logger.warning(f'split_into_columns(): dropped {i}')

    return column_items
