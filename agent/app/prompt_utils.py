import hashlib
from pathlib import Path


def load_prompt_raw() -> str:
    prompt_path = Path(__file__).resolve().parent / "agent_instructions.txt"
    return prompt_path.read_text(encoding="utf-8")


def compute_prompt_hash() -> str:
    prompt_text = load_prompt_raw()
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


def prompt_hash_changed(record, current_hash: str) -> bool:
    if not record:
        return True
    existing = record.get("prompt_hash")
    if not existing:
        return True
    return existing != current_hash
