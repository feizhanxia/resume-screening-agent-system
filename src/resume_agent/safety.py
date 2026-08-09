from __future__ import annotations

import html
import re
from typing import Any

_FORMULA_PREFIX = re.compile(r"^[\t\r\n ]*[=+\-@]")


def excel_safe_value(value: Any) -> Any:
    """Keep untrusted strings from being interpreted as spreadsheet formulas."""
    unsafe = isinstance(value, str) and (
        _FORMULA_PREFIX.match(value) or value.startswith(("\t", "\r", "\n"))
    )
    if unsafe:
        return "'" + value
    return value


def escape_rich_text(value: object) -> str:
    """Escape untrusted text before inserting it into Qt rich-text HTML."""
    return html.escape(str(value), quote=True)
