"""JSON responses that keep Decimals exact (serialised as strings, never floats)."""

from __future__ import annotations

from typing import Any

from fastapi import Response
from pydantic_core import to_json


def jsonify(content: Any, status_code: int = 200) -> Response:
    return Response(content=to_json(content), status_code=status_code, media_type="application/json")
