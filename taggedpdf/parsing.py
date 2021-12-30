# Support functions for parsing PDF structure

from pikepdf import Pdf, Dictionary, Array, String, Name

from .attribute import Attribute
from .logger import logger


def get_value(dictionary, key, type_, type_name, required, default):
    try:
        value = dictionary[key]
    except KeyError:
        if not required:
            return default
        else:
            msg = f'missing {key} in dictionary'
            logger.error(msg)
            raise ValueError(msg)
    if not isinstance(value, type_):
        try:
            value_type = value._type_name    # pikepdf types
        except:
            value_type = type(value).__name__
        msg = f'{key} has type "{value_type}", expected "{type_name}"'
        logger.error(msg)
        raise ValueError(msg)
    return value


def get_array(dictionary, key, required=False, default=None):
    type_, name = Array, 'array'
    return get_value(dictionary, key, type_, name, required, default)


def get_dictionary(dictionary, key, required=False, default=None):
    type_, name = Dictionary, 'dictionary'
    return get_value(dictionary, key, type_, name, required, default)


def get_name(dictionary, key, required=False, default=None):
    type_, name = Name, 'name'
    return get_value(dictionary, key, type_, name, required, default)


def get_integer(dictionary, key, required=False, default=None):
    type_, name = int, 'int'
    return get_value(dictionary, key, type_, name, required, default)


def get_string(dictionary, key, required=False, default=None):
    type_, name = String, 'string'    # NOTE: pikepdf String, not str
    return get_value(dictionary, key, type_, name, required, default)


def get_boolean(dictionary, key, required=False, default=False):
    type_, name = bool, 'bool'
    return get_value(dictionary, key, type_, name, required, default)


def parse_attributes(element):
    if element is None:
        return []
    elif isinstance(element, Dictionary):
        return parse_attributes_from_dict(element)
    elif isinstance(element, Array):
        return parse_attributes_from_array(element)
    else:
        raise NotImplementedError(f'attributes from {element._type_name}')


def parse_user_properties(dictionary: Dictionary):
    # See Reference Table 328 "Additional entries in an attribute
    # object dictionary for user properties"
    owner = get_name(dictionary, Name.O, required=True)
    assert owner == Name.UserProperties

    properties = get_array(dictionary, Name.P, required=True)

    # TODO parse properties array following Table 329 "Entries in
    # a user property dictionary"
    logger.warning('parsing of /UserProperties not implemented')
    return []


def parse_attributes_from_dict(dictionary: Dictionary):
    owner = get_name(dictionary, Name.O, required=True)
    if owner == Name.UserProperties:
        return parse_user_properties(dictionary)

    # For attributes other than user properties, entries other than
    # owner (O) represent the attributes. These are provided
    # here without checking conformance to the standard (see
    # 14.8.5 "Standard Structure Attributes" in Reference)
    return [
        Attribute(key, value, owner)
        for key, value in dictionary.items()
        if key != Name.O
    ]


def parse_attributes_from_array(array: Array):
    # TODO incomplete implementation
    attributes = []
    for i, item in enumerate(array):
        if isinstance(item, Dictionary):
            attributes.extend(parse_attributes_from_dict(item))
        elif isinstance(item, int):
            logger.warning('attribute revisions not implemented')    # TODO
        elif item is None:
            raise ValueError(f'None value in attributes')
        else:
            raise ValueError(f'wrong type in attributes: {item._type_name}')
    return attributes


def parse_attrib_class(element):
    if element is None:
        return []
    elif isinstance(element, Name):
        return [element]
    elif isinstance(element, Array):
        attrib_classes = []
        for item in element:
            if not isinstance(item, Name):
                raise ValueError(f'wrong type {item._type_name} in attr class')
            attrib_classes.append(item)
        return attrib_classes
    else:
        raise ValueError(f'wrong type {element._type_name} for attr class')
