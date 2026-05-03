"""Portable artifact extraction helpers for Lucy.

These helpers normalize the current PDF/blob/link handling logic in apex.py
so the runtime can surface non-text outputs without Chainlit-specific side
effects.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from .session import LucyArtifact

logger = logging.getLogger(__name__)


def _extract_filename_from_sas_url(sas_url: str) -> str:
    try:
        from urllib.parse import urlparse

        parsed_url = urlparse(sas_url)
        path = parsed_url.path.lstrip("/")
        path_parts = path.split("/")
        if len(path_parts) >= 2:
            filename = path_parts[-1]
            if filename.lower().endswith(".pdf"):
                return filename[:-4]
        if "/" in path:
            filename = path.split("/")[-1]
            if filename and filename.lower().endswith(".pdf"):
                return filename[:-4]
    except Exception as exc:
        logger.debug("Could not extract filename from SAS URL: %s", exc)
    return "Class Action Notice"


def extract_pdf_info_from_text(text: str) -> Optional[dict[str, str]]:
    """Extract PDF metadata from tool output or assistant text."""
    if not text:
        return None

    try:
        pdf_url_match = re.search(r"- PDF_URL: (.+)", text)
        pdf_name_match = re.search(r"- PDF_NAME: (.+)", text)
        display_match = re.search(r"- DISPLAY_MODE: (.+)", text)

        if pdf_url_match:
            pdf_url = pdf_url_match.group(1).strip()
            pdf_name = (
                pdf_name_match.group(1).strip()
                if pdf_name_match
                else _extract_filename_from_sas_url(pdf_url)
            )
            display_mode = display_match.group(1).strip() if display_match else "side"
            return {"url": pdf_url, "name": pdf_name, "display": display_mode}

        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
        for candidate in links:
            if "blob.core.windows.net" in candidate and "sig=" in candidate:
                return {
                    "url": candidate,
                    "name": _extract_filename_from_sas_url(candidate),
                    "display": "side",
                }
            if ".pdf" in candidate.lower():
                return {
                    "url": candidate,
                    "name": _extract_filename_from_sas_url(candidate),
                    "display": "side",
                }

        urls = re.findall(r"https?://[^\s\)\]\"'>]+", text)
        for candidate in urls:
            if "blob.core.windows.net" in candidate and "sig=" in candidate:
                return {
                    "url": candidate,
                    "name": _extract_filename_from_sas_url(candidate),
                    "display": "side",
                }
            if ".pdf" in candidate.lower():
                return {
                    "url": candidate,
                    "name": _extract_filename_from_sas_url(candidate),
                    "display": "side",
                }
    except Exception as exc:
        logger.warning("Failed to parse PDF info from text: %s", exc)
    return None


def _extract_links(text: str) -> list[str]:
    links: list[str] = []
    if not text:
        return links

    for candidate in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        links.append(candidate)
    for candidate in re.findall(r"https?://[^\s\)\]\"'>]+", text):
        links.append(candidate)
    return links


def _artifact_key(artifact: LucyArtifact) -> tuple[str, str | None]:
    return artifact.type, artifact.url


def _dedupe_artifacts(artifacts: list[LucyArtifact]) -> list[LucyArtifact]:
    deduped: list[LucyArtifact] = []
    seen: set[tuple[str, str | None]] = set()
    for artifact in artifacts:
        key = _artifact_key(artifact)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(artifact)
    return deduped


def extract_artifacts_from_text(text: str) -> list[LucyArtifact]:
    """Turn assistant text into portable artifacts when possible."""
    artifacts: list[LucyArtifact] = []
    pdf_info = extract_pdf_info_from_text(text)
    if pdf_info:
        artifacts.append(
            LucyArtifact(
                type="pdf",
                label=pdf_info["name"],
                url=pdf_info["url"],
                metadata={"display": pdf_info["display"]},
            )
        )

    pdf_url = pdf_info["url"] if pdf_info else None
    for link in _extract_links(text):
        if not link or link == pdf_url:
            continue
        label = link
        if "/" in link:
            label = link.rsplit("/", 1)[-1] or link
        artifacts.append(
            LucyArtifact(
                type="link",
                label=label,
                url=link,
            )
        )

    return _dedupe_artifacts(artifacts)

def extract_artifacts_from_tool_outputs(
    tool_outputs: list[dict[str, Any]],
    *,
    assistant_text: str | None = None,
) -> list[LucyArtifact]:
    """Aggregate artifacts from tool outputs and final assistant text."""
    artifacts: list[LucyArtifact] = []

    for call in tool_outputs or []:
        output = call.get("output")
        if output is None:
            continue
        if isinstance(output, (list, tuple)):
            output_text = "\n".join(str(item) for item in output if item is not None)
        else:
            output_text = str(output)
        artifacts.extend(extract_artifacts_from_text(output_text))

    if assistant_text:
        artifacts.extend(extract_artifacts_from_text(assistant_text))

    return _dedupe_artifacts(artifacts)
