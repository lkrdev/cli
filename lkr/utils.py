from collections.abc import Mapping, Sequence
from typing import Any

_MISSING = object()


def deep_get(obj: Any, path: str | Sequence[str | int], default: Any = None) -> Any:
    """Traverse dicts, sequences, and object attributes by dotted string or key sequence."""
    keys = path.split(".") if isinstance(path, str) else path
    cur = obj
    for key in keys:
        if cur is None:
            return default
        if isinstance(cur, Mapping):
            cur = cur.get(key, _MISSING)
        elif isinstance(cur, Sequence) and not isinstance(cur, (str, bytes)):
            try:
                idx = int(key)
                cur = cur[idx] if -len(cur) <= idx < len(cur) else _MISSING
            except (ValueError, TypeError):
                cur = getattr(cur, str(key), _MISSING)
        else:
            cur = getattr(cur, str(key), _MISSING)
        if cur is _MISSING:
            return default
    return cur
