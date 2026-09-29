# Copyright 2014 The Kubernetes Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
"""Conversion between selector objects and Selector.

Derived from k8s.io/apimachinery pkg/apis/meta/v1/helpers.go.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ._gofmt import go_quote
from .errors import SelectorError
from .labels import Labels, Requirement, Selector, everything, new_requirement, nothing, parse_requirements

LabelSelectorObject = Mapping[str, Any]
"""A ``metav1.LabelSelector`` as a mapping: ``matchLabels`` and ``matchExpressions`` (key, operator, values)."""

_OP_MAP = {"In": "in", "NotIn": "notin", "Exists": "exists", "DoesNotExist": "!"}


def _expressions(ps: LabelSelectorObject) -> Sequence[Mapping[str, Any]]:
    return ps.get("matchExpressions") or ()


def label_selector_as_selector(ps: LabelSelectorObject | None) -> Selector:
    """``metav1.LabelSelectorAsSelector``. None matches nothing; an empty selector matches everything.

    Raises :class:`SelectorError` with Go's message.
    """
    if ps is None:
        return nothing()
    match_labels: Mapping[str, str] = ps.get("matchLabels") or {}
    exprs = _expressions(ps)
    if len(match_labels) + len(exprs) == 0:
        return everything()
    reqs: list[Requirement] = []
    for k, v in match_labels.items():
        reqs.append(new_requirement(k, "=", [v]))
    for expr in exprs:
        operator = expr.get("operator", "")
        if operator not in _OP_MAP:
            raise SelectorError(f"{go_quote(operator)} is not a valid label selector operator")
        values = expr.get("values")
        reqs.append(new_requirement(expr.get("key", ""), _OP_MAP[operator], list(values) if values else None))
    return Selector().add(*reqs)


def label_selector_as_map(ps: LabelSelectorObject | None) -> dict[str, str] | None:
    """``metav1.LabelSelectorAsMap``: the old map-only form. Raises :class:`SelectorError` if impossible."""
    if ps is None:
        return None
    selector: dict[str, str] = dict(ps.get("matchLabels") or {})
    for expr in _expressions(ps):
        operator = expr.get("operator", "")
        if operator == "In":
            values: Sequence[str] = expr.get("values") or ()
            if len(values) != 1:
                raise SelectorError(
                    f"operator {go_quote(operator)} without a single value cannot be converted into the old label selector format"
                )
            selector[expr.get("key", "")] = values[0]
        elif operator in ("NotIn", "Exists", "DoesNotExist"):
            raise SelectorError(f"operator {go_quote(operator)} cannot be converted into the old label selector format")
        else:
            raise SelectorError(f"{go_quote(operator)} is not a valid selector operator")
    return selector


def parse_to_label_selector(selector: str) -> dict[str, Any]:
    """``metav1.ParseToLabelSelector``: a selector string as a LabelSelector dict."""
    try:
        reqs = parse_requirements(selector)
    except SelectorError as e:
        raise SelectorError(f'couldn\'t parse the selector string "{selector}": {e}') from None
    match_labels: dict[str, str] = {}
    match_expressions: list[dict[str, Any]] = []
    for req in reqs:
        if req.operator in ("=", "=="):
            vals = req.values()
            if len(vals) != 1:
                raise SelectorError("equals operator must have exactly one value")
            match_labels[req.key] = vals[0]
            continue
        names = {"in": "In", "notin": "NotIn", "exists": "Exists", "!": "DoesNotExist"}
        if req.operator in ("gt", "lt"):
            raise SelectorError(f"{go_quote(req.operator)} isn't supported in label selectors")
        if req.operator not in names:
            raise SelectorError(f"{go_quote(req.operator)} is not a valid label selector operator")
        match_expressions.append({"key": req.key, "operator": names[req.operator], "values": req.values()})
    return {"matchLabels": match_labels, "matchExpressions": match_expressions}


def set_as_label_selector(labels: Labels | None) -> dict[str, Any] | None:
    """``metav1.SetAsLabelSelector``."""
    if labels is None:
        return None
    return {"matchLabels": dict(labels)}


def format_label_selector(ps: LabelSelectorObject | None) -> str:
    """``metav1.FormatLabelSelector``: the selector string, ``<none>`` when empty, ``<error>`` when invalid."""
    try:
        s = str(label_selector_as_selector(ps))
    except SelectorError:
        return "<error>"
    return s or "<none>"
