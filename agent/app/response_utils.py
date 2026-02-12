import logging
from typing import Any, Iterable

logger = logging.getLogger("ResponseUtils")


def _iter_output_items(output: Any) -> Iterable[Any]:
    if output is None:
        return []
    if isinstance(output, list):
        return output
    return []


def _coerce_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        parts = []
        for item in value:
            if item is None:
                continue
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    if isinstance(value, dict):
        text = value.get("text")
        if text:
            return str(text)
    return str(value)


def extract_response_text(response: Any) -> str:
    """Extract response text from OpenAI Responses output.

    Prefers response.output_text when present; falls back to parsing message items.
    """
    output_text = getattr(response, "output_text", None)
    coerced = _coerce_text(output_text)
    if coerced:
        return coerced

    for item in _iter_output_items(getattr(response, "output", None)):
        if isinstance(item, dict) and item.get("type") == "message":
            for content in item.get("content", []) or []:
                if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                    text = content.get("text")
                    if text:
                        return str(text)
        else:
            # Handle SDK response items with attributes
            item_type = getattr(item, "type", None)
            if item_type == "message":
                for content in getattr(item, "content", []) or []:
                    content_type = getattr(content, "type", None)
                    if content_type in {"output_text", "text"}:
                        text = getattr(content, "text", None)
                        if text:
                            return str(text)

    logger.debug("Responses extraction returned empty text")
    return ""
