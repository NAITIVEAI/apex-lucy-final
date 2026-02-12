from typing import Any, Dict, Iterable, List
import re


def normalize_apex_token(value: str) -> str:
    if not value:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", str(value)).upper()


def apex_matches_result(apex_token: str, result: Dict[str, Any], allow_chunk: bool) -> bool:
    token = normalize_apex_token(apex_token)
    if not token:
        return False
    name_value = normalize_apex_token(result.get("metadata_storage_name", ""))
    path_value = normalize_apex_token(result.get("metadata_storage_path", ""))
    if token and (token in name_value or token in path_value):
        return True
    if allow_chunk:
        chunk_value = normalize_apex_token(result.get("chunk", ""))
        return token in chunk_value if token else False
    return False


def filter_results_by_apex(
    results: Iterable[Dict[str, Any]],
    apex_token: str,
    *,
    require_match: bool,
    allow_chunk: bool,
) -> List[Dict[str, Any]]:
    results_list = list(results or [])
    if not apex_token:
        return results_list
    matched = [r for r in results_list if apex_matches_result(apex_token, r, allow_chunk=allow_chunk)]
    if matched:
        return matched
    return [] if require_match else results_list
