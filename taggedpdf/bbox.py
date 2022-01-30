from typing import NamedTuple
from decimal import Decimal

from pikepdf import Name, Array


class BBox(NamedTuple):
    """Bounding box defined by its lower left and upper right coordinates."""
    llx: float
    lly: float
    urx: float
    ury: float

    @property
    def width(self):
        return self.urx-self.llx

    @property
    def height(self):
        return self.ury-self.lly

    @property
    def area(self):
        return self.width * self.height

    def contains(self, other):
        return self.intersection(other) == other

    def is_empty(self):
        return self.llx >= self.urx or self.lly >= self.ury

    def jaccard(self, other):
        isect_area = self.intersection(other).area
        union_area = self.area + other.area - isect_area
        return isect_area / union_area

    def relative_overlap(self, other):
        isect = self.intersection(other)
        if isect is None:
            return 0
        else:
            return isect.area / self.area

    def union(self, other):
        if isinstance(other, tuple):
            other = BBox(*other)
        return BBox.Union((self, other))

    def intersection(self, other):
        if isinstance(other, tuple):
            other = BBox(*other)
        return BBox.Intersection((self, other))

    def overlaps(self, other):
        return BBox.Intersection((self, other)) is not None

    def horizontally_overlaps(self, other):
        return self.llx < other.urx and other.llx < self.urx

    def vertically_overlaps(self, other):
        return self.lly < other.ury and other.lly < self.ury

    def is_above(self, other):
        return self.lly > other.ury

    def is_below(self, other):
        return other.is_above(self)

    def vertical_distance(self, other):
        if self.is_above(other):
            return self.lly - other.ury
        elif other.is_above(self):
            return other.lly - self.ury
        else:
            return None

    def coord_str(self):
        return f'{self.llx:.2f},{self.lly:.2f},{self.urx:.2f},{self.ury:.2f}'

    def padded(self, units):
        return BBox(
            self.llx - units,
            self.lly - units,
            self.urx + units,
            self.ury + units,
        )

    def to_coco(self, page_height):
        return [
            self.llx,
            page_height - self.ury,    # invert for y origin at page top
            self.urx-self.llx,
            self.ury-self.lly
        ]

    def __str__(self):
        return (
            f'BBox({self.llx:.1f}, {self.lly:.1f},'
            f' {self.urx:.1f}, {self.ury:.1f})'
        )

    def __repr__(self):
        return self.__str__()

    @classmethod
    def from_layout_items(cls, items):
        """Return union of BBoxes for pdfminer layout items."""
        return cls.Union([cls.from_layout_item(i) for i in items])

    @classmethod
    def from_layout_item(cls, item):
        """Return BBox for pdfminer layout item."""
        return cls(*item.bbox)

    @classmethod
    def from_string(cls, string):
        """Return BBox for string of four comma-separated coordinates."""
        coords = string.split(',')
        coords = [float(c) for c in coords]
        return cls(*coords)

    @classmethod
    def from_pikepdf_array(cls, array):
        """Return BBox for pikepdf Array."""
        assert len(array) == 4
        assert all(isinstance(i, (int, float, Decimal)) for i in array)
        coords = [float(i) for i in array]
        return cls(*coords)

    @classmethod
    def from_pikepdf_attribute(cls, attribute):
        """Return BBox for pikepdf BBox attribute."""
        assert attribute.name == Name.BBox
        assert isinstance(attribute.value, Array)
        return cls.from_pikepdf_array(attribute.value)

    @classmethod
    def from_layoutparser_block(cls, block, page_height):
        """Return BBox for Layout Parser layout block element."""
        x1, y1, x2, y2 = block.coordinates
        # Layout Parser y origin is at page top, so need to invert
        bottom, top = page_height-y2, page_height-y1
        return cls(x1, bottom, x2, top)

    @staticmethod
    def Union(bboxes):
        if not bboxes:
            return None
        return BBox(
            min(b.llx for b in bboxes),
            min(b.lly for b in bboxes),
            max(b.urx for b in bboxes),
            max(b.ury for b in bboxes),
        )

    @staticmethod
    def Intersection(bboxes):
        if not bboxes:
            return None
        isect = BBox(
            max(b.llx for b in bboxes),
            max(b.lly for b in bboxes),
            min(b.urx for b in bboxes),
            min(b.ury for b in bboxes),
        )
        if isect.is_empty():
            return None
        else:
            return isect

