from __future__ import annotations

from typing import Tuple, Type


def load_otel_status() -> Tuple[Type, Type]:
    try:
        from opentelemetry.trace import Status, StatusCode
        return Status, StatusCode
    except Exception:
        class Status:
            def __init__(self, code, description=None):
                self.code = code
                self.description = description

        class StatusCode:
            OK = 0
            ERROR = 1

        return Status, StatusCode
