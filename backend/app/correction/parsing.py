"""Strict parsing of a provider's JSON response.

The model is asked for a bare JSON object. This module tolerates a fenced
code block or stray prose around the object, then requires a real JSON object.
Anything else raises :class:`InvalidEngineOutput`; the raw response is never
logged or echoed to the user.
"""

from __future__ import annotations

import json

from ..engine import InvalidEngineOutput

_INVALID = "The AI provider returned a response that was not valid JSON."


def parse_json_object(text: str) -> dict:
    """Return the JSON object contained in ``text``.

    Raises :class:`InvalidEngineOutput` when no object can be decoded.
    """
    if not isinstance(text, str) or not text.strip():
        raise InvalidEngineOutput(_INVALID)

    candidates: list[str] = []
    stripped = text.strip()

    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            body = "\n".join(lines[1:])
            if body.rstrip().endswith("```"):
                body = body.rstrip()[:-3]
            candidates.append(body.strip())

    candidates.append(stripped)

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start : end + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict):
            return payload

    raise InvalidEngineOutput(_INVALID)
