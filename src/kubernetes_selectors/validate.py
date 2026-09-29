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
# limitations under the License.
"""Label key and value validation.

Derived from k8s.io/apimachinery pkg/api/validate/content (kube.go, dns.go, errors.go).
The regular expressions are replaced by linear scans so that long inputs cannot backtrack.
"""

from __future__ import annotations

from ._gofmt import byte_length

_LABEL_KEY_FMT = "([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9]"
_LABEL_KEY_ERR = (
    "must consist of alphanumeric characters, '-', '_' or '.', "
    "and must start and end with an alphanumeric character"
)
_LABEL_VALUE_FMT = "(" + _LABEL_KEY_FMT + ")?"
_LABEL_VALUE_ERR = (
    "a valid label must be an empty string or consist of alphanumeric characters, '-', '_' or '.', "
    "and must start and end with an alphanumeric character"
)
_DNS_LABEL_FMT = "[a-z0-9]([-a-z0-9]*[a-z0-9])?"
_DNS_SUBDOMAIN_FMT = _DNS_LABEL_FMT + "(\\." + _DNS_LABEL_FMT + ")*"
_DNS_SUBDOMAIN_ERR = (
    "a lowercase RFC 1123 subdomain must consist of lower case alphanumeric characters, '-' or '.', "
    "and must start and end with an alphanumeric character"
)

_ALNUM = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
_LOWER_ALNUM = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
_NAME_EXT = _ALNUM | frozenset("-_.")
_DNS_EXT = _LOWER_ALNUM | frozenset("-")


def _max_len_error(length: int) -> str:
    return f"must be no more than {length} bytes"


def _regex_error(msg: str, regex: str, *examples: str) -> str:
    if not examples:
        return msg + " (regex used for validation is '" + regex + "')"
    msg += " (e.g. "
    for i, ex in enumerate(examples):
        if i > 0:
            msg += " or "
        msg += "'" + ex + "', "
    return msg + "regex used for validation is '" + regex + "')"


def _is_name_part(s: str) -> bool:
    """Matches ``([A-Za-z0-9][-A-Za-z0-9_.]*)?[A-Za-z0-9]``."""
    if not s or s[0] not in _ALNUM or s[-1] not in _ALNUM:
        return False
    return all(c in _NAME_EXT for c in s[1:-1])


def _is_dns_label(s: str) -> bool:
    """Matches ``[a-z0-9]([-a-z0-9]*[a-z0-9])?``."""
    if not s or s[0] not in _LOWER_ALNUM or s[-1] not in _LOWER_ALNUM:
        return False
    return all(c in _DNS_EXT for c in s[1:-1])


def _is_dns1123_subdomain(value: str) -> list[str]:
    errs: list[str] = []
    if byte_length(value) > 253:
        errs.append(_max_len_error(253))
    if not all(_is_dns_label(p) for p in value.split(".")):
        errs.append(_regex_error(_DNS_SUBDOMAIN_ERR, _DNS_SUBDOMAIN_FMT, "example.com"))
    return errs


def validate_label_key(value: str) -> list[str]:
    """Errors for a label key, as ``content.IsLabelKey`` (``validation.IsQualifiedName``) reports them.

    An empty list means the key is valid.
    """
    errs: list[str] = []
    parts = value.split("/")
    if len(parts) == 1:
        name = parts[0]
    elif len(parts) == 2:
        prefix, name = parts
        if not prefix:
            errs.append("prefix part must be non-empty")
        else:
            errs.extend("prefix part " + m for m in _is_dns1123_subdomain(prefix))
    else:
        errs.append(
            "a valid label key "
            + _regex_error(_LABEL_KEY_ERR, _LABEL_KEY_FMT, "MyName", "my.name", "123-abc")
            + " with an optional DNS subdomain prefix and '/' (e.g. 'example.com/MyName')"
        )
        return errs
    if not name:
        errs.append("name part must be non-empty")
    elif byte_length(name) > 63:
        errs.append("name part " + _max_len_error(63))
    if not _is_name_part(name):
        errs.append("name part " + _regex_error(_LABEL_KEY_ERR, _LABEL_KEY_FMT, "MyName", "my.name", "123-abc"))
    return errs


def validate_label_value(value: str) -> list[str]:
    """Errors for a label value, as ``content.IsLabelValue`` (``validation.IsValidLabelValue``) reports them.

    An empty list means the value is valid.
    """
    errs: list[str] = []
    if byte_length(value) > 63:
        errs.append(_max_len_error(63))
    if value != "" and not _is_name_part(value):
        errs.append(_regex_error(_LABEL_VALUE_ERR, _LABEL_VALUE_FMT, "MyValue", "my_value", "12345"))
    return errs
