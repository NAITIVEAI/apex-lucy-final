from typing import Dict


def build_progress_props(label: str, value: int) -> Dict[str, int | str]:
    value = max(0, min(100, int(value)))
    return {"label": label, "value": value}
