from typing import Tuple, Type


def get_status_classes() -> Tuple[Type, Type]:
    try:
        from opentelemetry.trace import Status, StatusCode  # type: ignore
        return Status, StatusCode
    except Exception:
        class Status:  # pragma: no cover - fallback
            def __init__(self, code, description=None):
                self.code = code
                self.description = description

        class StatusCode:  # pragma: no cover - fallback
            OK = 0
            ERROR = 1

        return Status, StatusCode
