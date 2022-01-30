# Common configuration options


# Annotation categories for COCO output (TODO: move to different file)
COCO_CATEGORIES = [
    {
      "id": 0,
      "name": "Paragraph",
      "supercategory": None
    },
    {
      "id": 1,
      "name": "Title",
      "supercategory": None
    },
    {
      "id": 2,
      "name": "ListItem",
      "supercategory": None
    },
    {
      "id": 3,
      "name": "Table",
      "supercategory": None
    },
    {
      "id": 4,
      "name": "Figure",
      "supercategory": None
    },
    {
      "id": 5,
      "name": "Meta",
      "supercategory": None
    },
    {
      "id": 6,
      "name": "Reference",
      "supercategory": None
    },
    {
      "id": 7,
      "name": "Footnote",
      "supercategory": None
    },
    {
      "id": 8,
      "name": "TableOfContents",
      "supercategory": None
    },
    {
      "id": 9,
      "name": "Caption",
      "supercategory": None
    }
    {
      "id": 10,
      "name": "Formula",
      "supercategory": None
    }
    {
      "id": 11,
      "name": "Code",
      "supercategory": None
    }
    {
      "id": 12,
      "name": "Other",
      "supercategory": None
    }
]


# Mapping from structure types to annotation labels
STRUCT_TYPE_TO_LABEL_MAP = {
    'P': 'Paragraph',
    'LI': 'ListItem',
    'H1': 'Title',
    'H2': 'Title',
    'H3': 'Title',
    'H4': 'Title',
    'H5': 'Title',
    'H6': 'Title',
    'TOC': 'TableOfContents',
    'TOCI': 'TocItem',
    'Table': 'Table',
    'Figure': 'Figure',
    'Footnote': 'Footnote',
    'Note': 'Footnote',
}


# Colors for annotations
LABEL_TO_HEX_COLOR_MAP = {
    'Paragraph': '#24DD24',
    'Title': '#6FDECD',
    'ListItem': '#D0EC37',
    'Table' : '#EC3737',
    'TableOfContents': '#DDBD24',
    'TocItem': '#CCAD14',
    'Figure': '#375BEC',
    'Reference': '#EC9937',
    'Footnote': '#777777',
    'Note': '#777777',
    'Caption': '#E186C0',
}


LABEL_TO_COLOR_MAP = {
    k: (int(v[1:3],16)/255, int(v[3:5],16)/255, int(v[5:7],16)/255)
    for k, v in LABEL_TO_HEX_COLOR_MAP.items()
}


LABEL_FONT_NAME = 'Courier'


LABEL_FONT_SIZE = 6
