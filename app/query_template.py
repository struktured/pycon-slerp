"""PEP 750-style structured query templating for SerpApi searches.

Credit: PEP 750 ("t-strings") talk at PyCon US 2026, by Vinicus Gubiana Ferreria.

PEP 750 ships in Python 3.14 as `string.templatelib`. The literal `t"..."`
syntax requires the 3.14 parser, but the *idea* — defer rendering of an
interpolated string so the processor can apply context-aware escaping per
slot — works on any Python. This module is that idea, applied to SerpApi
query construction.

Why it matters here: the previous code interpolated speaker names into
search queries with f-strings:

    follow_up = f'"{speaker_label}" PyCon python'

If a speaker label contains a stray double-quote, that f-string silently
produces a malformed query (or worse, an injection that changes the search
intent). The same SQL/XSS problem t-strings were designed to solve, just
applied to search-engine queries.

Usage:

    >>> safe_query('"{speaker}" PyCon python', speaker='Carol "Cara" Willing')
    '"Carol Cara Willing" PyCon python'
"""
from __future__ import annotations

import re
import string


# Try the real 3.14 stdlib first; fall back to a polyfill on older Pythons.
try:
    from string.templatelib import Template  # noqa: F401  (3.14+)
    HAS_TEMPLATELIB = True
except ImportError:
    HAS_TEMPLATELIB = False


_BAD_QUERY_CHARS = re.compile(r'["\'\\\n\r\t]')


def _escape_query_value(value: object) -> str:
    """Context-aware escaper for a SerpApi search query slot.

    Strip characters that would break out of the quoted phrase or confuse
    the search engine. We don't want injections, just safe interpolation.
    """
    return _BAD_QUERY_CHARS.sub("", str(value)).strip()


def safe_query(template: str, **values: object) -> str:
    """Render `template` with named slots, escaping each value for SerpApi.

    Slot syntax: `{name}` (same as `str.format`). The escape pass runs on
    each slot *before* substitution — the structure stays in the template,
    the user-supplied values get sanitized.

    This is the t-strings pattern: defer rendering, hand the structure to
    a context-aware processor, apply per-slot escaping. PEP 750 with a
    polyfill for sub-3.14 Pythons.
    """
    formatter = string.Formatter()
    out: list[str] = []
    for literal, field, fmt, conv in formatter.parse(template):
        if literal:
            out.append(literal)
        if field is not None:
            if field not in values:
                raise KeyError(f"safe_query: missing value for slot {field!r}")
            out.append(_escape_query_value(values[field]))
    return "".join(out)
