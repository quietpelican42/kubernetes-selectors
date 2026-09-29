"""Exception type for rejected selectors."""

from __future__ import annotations


class SelectorError(ValueError):
    """Raised for every selector or requirement that apimachinery rejects.

    ``str(error)`` is the text Go's ``err.Error()`` returns.
    """
