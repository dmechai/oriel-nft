from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone


def uid() -> str:
    return uuid.uuid4().hex


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def dumps(data) -> str:
    return json.dumps(data, ensure_ascii=False)


def loads(raw: str | None, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback
