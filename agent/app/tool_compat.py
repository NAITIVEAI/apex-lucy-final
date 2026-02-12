from __future__ import annotations

from typing import Any, Optional


def should_add_ai_search_tool(model: Optional[str], ai_search_tool: Optional[Any]) -> bool:
    if ai_search_tool is None:
        return False
    if not model:
        return True
    model_lower = model.lower()
    if model_lower.startswith("gpt-5"):
        return False
    return True
