"""Kubernetes label and field selectors with the behavior of k8s.io/apimachinery."""

from .errors import SelectorError
from .fields import (
    FieldRequirement,
    Fields,
    FieldSelector,
    escape_field_value,
    everything_fields,
    field_selector_from_set,
    nothing_fields,
    parse_field_selector,
    unescape_field_value,
)
from .labelselector import (
    LabelSelectorObject,
    format_label_selector,
    label_selector_as_map,
    label_selector_as_selector,
    parse_to_label_selector,
    set_as_label_selector,
)
from .labels import (
    Labels,
    Requirement,
    Selector,
    everything,
    matches,
    new_requirement,
    nothing,
    parse_requirements,
    parse_selector,
    selector_from_set,
    validated_selector_from_set,
)
from .validate import validate_label_key, validate_label_value

__all__ = [
    "FieldRequirement",
    "FieldSelector",
    "Fields",
    "LabelSelectorObject",
    "Labels",
    "Requirement",
    "Selector",
    "SelectorError",
    "escape_field_value",
    "everything",
    "everything_fields",
    "field_selector_from_set",
    "format_label_selector",
    "label_selector_as_map",
    "label_selector_as_selector",
    "matches",
    "new_requirement",
    "nothing",
    "nothing_fields",
    "parse_field_selector",
    "parse_requirements",
    "parse_selector",
    "parse_to_label_selector",
    "selector_from_set",
    "set_as_label_selector",
    "unescape_field_value",
    "validate_label_key",
    "validate_label_value",
    "validated_selector_from_set",
]
