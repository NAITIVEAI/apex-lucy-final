from typing import Optional


def should_include_max_output_tokens(value: Optional[str]) -> Optional[int]:
    """Return None to disable max_output_tokens unless explicitly re-enabled later."""
    return None
