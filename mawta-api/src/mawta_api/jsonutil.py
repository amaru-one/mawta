"""One JSON encoding for everything the service writes: API responses, jsonb columns, logs.

UUIDs are strings, timestamps are RFC 3339 in UTC, dates are YYYY-MM-DD and numerics
are plain numbers.
"""

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from psycopg.types.json import Jsonb


def rfc3339(value: datetime) -> str:
    """The API's timestamp form: UTC, RFC 3339 with the shortest fractional second."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    value = value.astimezone(UTC)
    text = value.strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond:
        text += f".{value.microsecond:06d}".rstrip("0")
    return text + "Z"


def _default(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return rfc3339(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(f"{type(value).__name__} is not JSON serialisable")


def dumps_str(value: Any) -> str:
    return json.dumps(value, default=_default, ensure_ascii=False, separators=(",", ":"))


def dumps(value: Any) -> bytes:
    return dumps_str(value).encode()


def jsonb(value: Any) -> Jsonb:
    """A jsonb parameter that encodes UUIDs, dates and decimals like the API does."""
    return Jsonb(value, dumps=dumps_str)
