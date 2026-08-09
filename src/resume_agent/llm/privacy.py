from __future__ import annotations

import re

PATTERNS = (
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号已脱敏]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[邮箱已脱敏]"),
    (re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"), "[身份证号已脱敏]"),
)


def redact_pii(text: str) -> str:
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_secret(text: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9_-]{12,}", "sk-***", text)
