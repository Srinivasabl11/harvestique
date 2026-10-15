"""Read the JSON object a vision model returned, as the model actually sends it.

Ollama's `format` (JSON schema) is enforced by a local Ollama server, but Ollama Cloud's gemma4:31b returns the same
object wrapped in a Markdown fence (```json ... ```), and other models may add a sentence before or after it. On
2026-10-16 every production photo check failed as "invalid_response" for exactly this reason.

Accepted: a bare object, a fenced object, or one object surrounded by text. Everything else still raises ValueError:
no object, several top-level objects, an array, or broken JSON. The caller then validates every field (interpret()).
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*\n?(.*?)\n?\s*```$", re.DOTALL)
_DECODER = json.JSONDecoder()


def parse_model_json(text: str) -> dict[str, Any]:
    if not isinstance(text, str):
        raise ValueError("the model answer is not text")
    s = text.strip()
    fenced = _FENCE.match(s)
    if fenced:
        s = fenced.group(1).strip()
    try:
        value = json.loads(s)
    except json.JSONDecodeError:
        value = _single_embedded_object(s)
    if not isinstance(value, dict):
        raise ValueError("the model answer is not a JSON object")
    return value


def _single_embedded_object(s: str) -> Any:
    """The one JSON object inside surrounding text; two objects are ambiguous and refused."""
    start = s.find("{")
    if start < 0:
        raise ValueError("no JSON object in the model answer")
    value, end = _DECODER.raw_decode(s, start)
    if "{" in s[end:]:
        raise ValueError("more than one JSON object in the model answer")
    return value
