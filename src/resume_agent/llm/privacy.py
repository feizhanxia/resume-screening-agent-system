from __future__ import annotations

import re

PATTERNS = (
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "[手机号已脱敏]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[邮箱已脱敏]"),
    (re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)"), "[身份证号已脱敏]"),
    (
        re.compile(r"(?im)(?:姓名|name)\s*[:：]\s*[^\n,，;；]{2,40}"),
        "姓名：[姓名已脱敏]",
    ),
    (
        re.compile(r"(?m)(?:住址|地址|现居地|所在地)\s*[:：]\s*[^\n,，;；]{4,100}"),
        "地址：[地址已脱敏]",
    ),
)


def redact_pii(text: str, explicit_names: tuple[str, ...] = ()) -> str:
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    for name in explicit_names:
        if 2 <= len(name.strip()) <= 80:
            text = text.replace(name.strip(), "[姓名已脱敏]")
    return text


def redact_secret(text: str) -> str:
    return re.sub(r"sk-[A-Za-z0-9_-]{12,}", "sk-***", text)
