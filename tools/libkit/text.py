"""Generated description and search keywords for a part."""

from __future__ import annotations

from collections import defaultdict

from .parts import Part
from .schema import Schema
from .values import parse_value, spellings


def _deprecated(part: Part) -> bool:
    return part.data.get("status") == "deprecated"


def build_description(part: Part, schema: Schema) -> str:
    cat = schema.categories[part.category]
    text = part.data.get("description", "")
    if not text and cat.description_template:
        text = cat.description_template.format_map(defaultdict(str, part.data))
    text = " ".join(text.split())
    return f"DEPRECATED {text}".strip() if _deprecated(part) else text


def build_keywords(part: Part, schema: Schema) -> str:
    if _deprecated(part):
        return ""
    cat = schema.categories[part.category]
    tokens: list[str] = []
    value = part.data.get("value", "")
    if value:
        if cat.value_unit:
            try:
                tokens += spellings(parse_value(value, cat.value_unit), cat.value_unit)
            except ValueError:
                tokens.append(value)
        else:
            tokens.append(value)
    for f in schema.fields_for(cat):
        if f.keyword and part.data.get(f.key):
            tokens.append(part.data[f.key])
    return " ".join(dict.fromkeys(tokens))
