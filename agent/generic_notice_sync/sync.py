"""Sync generic case notice PDFs from SharePoint to Azure Blob Storage.

This job intentionally copies only the case-level generic notice packet PDFs
from each case folder. It does not restore the old per-class-member mail merge
sync.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import quote

import requests


LOG = logging.getLogger("generic_notice_sync")

DEFAULT_SITE_HOST = "apexclassaction.sharepoint.com"
DEFAULT_SITE_PATH = "/sites/ApexClassAction"
DEFAULT_CASE_ROOT = "/Shared Documents/Active Cases/Settlements"
DEFAULT_DRIVE_NAME = "Documents"
DEFAULT_NOTICE_SUBPATH = "Print/Notice packet"
DEFAULT_DESTINATION_CONTAINER = "lucycmnotices"
DEFAULT_BLOB_PREFIX = "generic-notices"
DEFAULT_LEDGER_BLOB = "_sync/generic_notice_ledger.json"
EXCLUDED_SOURCE_NAME_TERMS = ("mail merge", "for merge", "with ssn", "ssn")
GENERIC_NOTICE_TRAILING_TERMS = (
    "class",
    "copy",
    "draft",
    "en",
    "english",
    "es",
    "final",
    "form",
    "mailing",
    "merge",
    "notice",
    "packet",
    "pdf",
    "redacted",
    "remail",
    "revised",
    "revision",
    "settlement",
    "short",
    "spanish",
    "version",
    "working",
)


@dataclass(frozen=True)
class SyncConfig:
    site_host: str = DEFAULT_SITE_HOST
    site_path: str = DEFAULT_SITE_PATH
    drive_name: str = DEFAULT_DRIVE_NAME
    case_root_path: str = DEFAULT_CASE_ROOT
    notice_subpath: str = DEFAULT_NOTICE_SUBPATH
    destination_container: str = DEFAULT_DESTINATION_CONTAINER
    destination_prefix: str = DEFAULT_BLOB_PREFIX
    ledger_blob: str = DEFAULT_LEDGER_BLOB
    dry_run: bool = False

    @classmethod
    def from_env(cls, *, dry_run: bool = False) -> "SyncConfig":
        return cls(
            site_host=os.getenv("SHAREPOINT_SITE_HOST", DEFAULT_SITE_HOST),
            site_path=os.getenv("SHAREPOINT_SITE_PATH", DEFAULT_SITE_PATH),
            drive_name=os.getenv("SHAREPOINT_DRIVE_NAME", DEFAULT_DRIVE_NAME),
            case_root_path=os.getenv("SHAREPOINT_CASE_ROOT", DEFAULT_CASE_ROOT),
            notice_subpath=os.getenv("GENERIC_NOTICE_SUBPATH", DEFAULT_NOTICE_SUBPATH),
            destination_container=(
                os.getenv("AZURE_GENERIC_NOTICE_CONTAINER")
                or os.getenv("AZURE_STORAGE_CONTAINER_NAME")
                or DEFAULT_DESTINATION_CONTAINER
            ),
            destination_prefix=os.getenv("GENERIC_NOTICE_BLOB_PREFIX", DEFAULT_BLOB_PREFIX),
            ledger_blob=os.getenv("GENERIC_NOTICE_LEDGER_BLOB", DEFAULT_LEDGER_BLOB),
            dry_run=dry_run,
        )


def slugify_case_name(case_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", case_name).strip("-").lower()
    return slug or "unknown-case"


def case_identity_key(case_name: str, *, source_item_id: str | None = None) -> str:
    normalized = unicodedata.normalize(
        "NFKD",
        f"{str(case_name or '').strip()}|{str(source_item_id or '').strip()}",
    )
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = " ".join(ascii_value.lower().split())
    return hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:8]


def normalize_drive_relative_path(path: str, drive_name: str = DEFAULT_DRIVE_NAME) -> str:
    cleaned = (path or "").strip().strip("/")
    drive_aliases = {
        (drive_name or "").strip().lower(),
        "documents",
        "shared documents",
    }
    parts = [part for part in cleaned.split("/") if part]
    if parts and parts[0].lower() in drive_aliases:
        parts = parts[1:]
    return "/".join(parts)


def build_notice_packet_path(case_name: str, config: SyncConfig) -> str:
    root = normalize_drive_relative_path(config.case_root_path, config.drive_name)
    suffix = config.notice_subpath.strip("/")
    return "/".join(part for part in (root, case_name, suffix) if part)


def build_print_folder_path(case_name: str, config: SyncConfig) -> str:
    root = normalize_drive_relative_path(config.case_root_path, config.drive_name)
    return "/".join(part for part in (root, case_name, "Print") if part)


def destination_pdf_name(file_name: str) -> str:
    stem = re.sub(r"\.[^.]+$", "", (file_name or "").strip())
    return f"{stem or 'Notice Packet'}.pdf"


def generic_notice_case_key(case_name: str, *, source_item_id: str | None = None) -> str:
    return f"{slugify_case_name(case_name)}--{case_identity_key(case_name, source_item_id=source_item_id)}"


def generic_notice_rag_key(case_name: str, *, source_item_id: str | None = None) -> str:
    return generic_notice_case_key(case_name, source_item_id=source_item_id)


def build_destination_blob_name(
    case_name: str,
    file_name: str,
    prefix: str = DEFAULT_BLOB_PREFIX,
    *,
    source_item_id: str | None = None,
) -> str:
    prefix = (prefix or "").strip("/")
    flat_file = f"{generic_notice_case_key(case_name, source_item_id=source_item_id)}--generic-notice.pdf"
    parts = [part for part in (prefix, flat_file) if part]
    return "/".join(parts)


def blob_metadata_value(value: Any, *, max_length: int = 1024) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return normalized.encode("ascii", "ignore").decode("ascii")[:max_length]


def item_fingerprint(item: dict[str, Any]) -> dict[str, Any]:
    hashes = item.get("file", {}).get("hashes", {}) if isinstance(item.get("file"), dict) else {}
    return {
        "id": item.get("id"),
        "eTag": item.get("eTag"),
        "cTag": item.get("cTag"),
        "size": item.get("size"),
        "lastModifiedDateTime": item.get("lastModifiedDateTime"),
        "sha1Hash": hashes.get("sha1Hash"),
        "quickXorHash": hashes.get("quickXorHash"),
    }


def should_upload(item: dict[str, Any], ledger_entry: dict[str, Any] | None) -> bool:
    if not ledger_entry:
        return True
    return item_fingerprint(item) != ledger_entry.get("source")


class GraphClient:
    def __init__(self, token: str, *, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()
        self._session.headers.update({"Authorization": f"Bearer {token}"})

    @classmethod
    def from_azure_identity(cls) -> "GraphClient":
        from azure.identity import ClientSecretCredential, DefaultAzureCredential

        tenant_id = os.getenv("GRAPH_TENANT_ID") or os.getenv("AZURE_TENANT_ID")
        client_id = os.getenv("GRAPH_CLIENT_ID") or os.getenv("AZURE_CLIENT_ID")
        client_secret = os.getenv("GRAPH_CLIENT_SECRET") or os.getenv("AZURE_CLIENT_SECRET")
        if tenant_id and client_id and client_secret:
            credential = ClientSecretCredential(tenant_id, client_id, client_secret)
        else:
            credential = DefaultAzureCredential(exclude_shared_token_cache_credential=False)
        token = credential.get_token("https://graph.microsoft.com/.default").token
        return cls(token)

    def get_json(self, url: str) -> dict[str, Any]:
        response = self._session.get(url, timeout=60)
        response.raise_for_status()
        return response.json()

    def get_all(self, url: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        next_url: str | None = url
        while next_url:
            payload = self.get_json(next_url)
            items.extend(payload.get("value", []))
            next_url = payload.get("@odata.nextLink")
        return items

    def download_file(self, drive_id: str, item_id: str, *, as_pdf: bool = False) -> bytes:
        suffix = "?format=pdf" if as_pdf else ""
        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content{suffix}"
        response = self._session.get(url, timeout=180, allow_redirects=True)
        response.raise_for_status()
        return response.content


def graph_path_children_url(drive_id: str, path: str) -> str:
    quoted_path = quote(path.strip("/"), safe="/")
    return f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{quoted_path}:/children"


def get_site_id(graph: GraphClient, config: SyncConfig) -> str:
    site_path = config.site_path.strip("/")
    url = f"https://graph.microsoft.com/v1.0/sites/{config.site_host}:/{site_path}"
    return graph.get_json(url)["id"]


def get_drive_id(graph: GraphClient, site_id: str, drive_name: str) -> str:
    drives = graph.get_all(f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives")
    preferred = (drive_name or "").strip().lower()
    for drive in drives:
        if str(drive.get("name", "")).strip().lower() == preferred:
            return str(drive["id"])
    for drive in drives:
        if str(drive.get("driveType", "")).lower() == "documentlibrary":
            return str(drive["id"])
    raise RuntimeError(f"No SharePoint document library drive found for {site_id}")


def list_case_folders(graph: GraphClient, drive_id: str, config: SyncConfig) -> list[dict[str, Any]]:
    root = normalize_drive_relative_path(config.case_root_path, config.drive_name)
    children = graph.get_all(graph_path_children_url(drive_id, root))
    return [item for item in children if "folder" in item]


def list_notice_pdfs(
    graph: GraphClient,
    drive_id: str,
    case_folder_name: str,
    config: SyncConfig,
) -> list[dict[str, Any]]:
    notice_path = build_notice_packet_path(case_folder_name, config)
    try:
        children = graph.get_all(graph_path_children_url(drive_id, notice_path))
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        LOG.debug("No notice packet folder for case=%s status=%s", case_folder_name, status)
        children = []
    notice_items = [
        item
        for item in children
        if "file" in item and _is_case_level_notice_source_file(str(item.get("name", "")))
    ]
    if notice_items:
        return [_select_best_notice_source(notice_items)]

    print_path = build_print_folder_path(case_folder_name, config)
    try:
        print_children = graph.get_all(graph_path_children_url(drive_id, print_path))
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        LOG.debug("No Print folder for case=%s status=%s", case_folder_name, status)
        return []

    print_notice_items = [
        item
        for item in print_children
        if "file" in item and _is_notice_packet_file(str(item.get("name", "")))
    ]
    if not print_notice_items:
        return []
    return [_select_best_notice_source(print_notice_items)]


def _is_supported_notice_source_file(file_name: str) -> bool:
    lowered = file_name.lower()
    if any(term in lowered for term in EXCLUDED_SOURCE_NAME_TERMS):
        return False
    return lowered.endswith((".pdf", ".doc", ".docx"))


def _is_case_level_notice_source_file(file_name: str) -> bool:
    if not _is_supported_notice_source_file(file_name):
        return False
    return not _looks_like_member_specific_notice_name(file_name)


def _is_notice_packet_file(file_name: str) -> bool:
    lowered = file_name.lower()
    if not _is_case_level_notice_source_file(file_name):
        return False
    return "notice" in lowered


def _is_person_name_fragment(value: str) -> bool:
    fragment = (value or "").strip(" '\"")
    if not fragment or re.search(r"\d", fragment):
        return False
    lowered = fragment.lower()
    business_terms = {
        "agency",
        "authority",
        "case",
        "center",
        "company",
        "contractors",
        "corp",
        "corporation",
        "group",
        "health",
        "hospital",
        "inc",
        "llc",
        "lp",
        "ltd",
        "management",
        "medical",
        "services",
        "systems",
    }
    if any(term in lowered.split() for term in business_terms):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z']+", fragment)
    if len(words) < 2 or len(words) > 4:
        return False
    lowered_words = {word.lower() for word in words}
    if lowered_words.intersection(GENERIC_NOTICE_TRAILING_TERMS):
        return False
    short_words = {"a", "d", "de", "del", "di", "la", "le", "van", "von"}
    return all(
        word.lower() in short_words or (word[0].isupper() and not word.isupper())
        for word in words
    )


def _looks_like_member_specific_notice_name(file_name: str) -> bool:
    stem = re.sub(r"\.[^.]+$", "", (file_name or "").strip())
    parts = [part.strip(" '\"") for part in re.split(r"\s[-–—]\s", stem) if part.strip()]
    if len(parts) < 2:
        return False

    if _is_person_name_fragment(parts[-1]):
        return True
    first_words = re.findall(r"[A-Za-z]+", parts[0])
    has_middle_initial = bool(re.search(r"\b[A-Z]\b", parts[0]))
    strong_leading_name = len(first_words) >= 3 or has_middle_initial
    return (
        "notice" in " ".join(parts[1:]).lower()
        and strong_leading_name
        and _is_person_name_fragment(parts[0])
    )


def _notice_source_score(item: dict[str, Any]) -> tuple[int, str]:
    name = str(item.get("name", ""))
    lowered = name.lower()
    score = 0
    if lowered.endswith(".pdf"):
        score += 40
    if lowered.endswith((".doc", ".docx")):
        score += 20
    if "notice packet" in lowered:
        score += 30
    if "class notice packet" in lowered:
        score += 35
    if "class notice" in lowered:
        score += 25
    if any(term in lowered for term in EXCLUDED_SOURCE_NAME_TERMS):
        score -= 1000
    if _looks_like_member_specific_notice_name(name):
        score -= 500
    if "copy" in lowered:
        score -= 20
    if "old" in lowered or "draft" in lowered:
        score -= 30
    return score, name.lower()


def _select_best_notice_source(items: list[dict[str, Any]]) -> dict[str, Any]:
    """Select exactly one generic notice source per case."""
    if not items:
        raise ValueError("Cannot select a notice source from an empty list")
    return sorted(items, key=_notice_source_score, reverse=True)[0]


def get_blob_service_client():
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient

    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if connection_string:
        return BlobServiceClient.from_connection_string(connection_string)
    account_name = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    if not account_name:
        raise RuntimeError("AZURE_STORAGE_ACCOUNT_NAME or AZURE_STORAGE_CONNECTION_STRING is required")
    return BlobServiceClient(
        f"https://{account_name}.blob.core.windows.net",
        credential=DefaultAzureCredential(exclude_shared_token_cache_credential=False),
    )


def content_settings(content_type: str):
    from azure.storage.blob import ContentSettings

    return ContentSettings(content_type=content_type)


def load_ledger(container_client, ledger_blob: str) -> dict[str, Any]:
    try:
        payload = container_client.get_blob_client(ledger_blob).download_blob().readall()
    except Exception:
        return {"version": 1, "files": {}}
    try:
        ledger = json.loads(payload.decode("utf-8"))
    except Exception:
        LOG.warning("Ledger blob was unreadable; starting with an empty ledger")
        return {"version": 1, "files": {}}
    ledger.setdefault("version", 1)
    ledger.setdefault("files", {})
    return ledger


def save_ledger(container_client, ledger_blob: str, ledger: dict[str, Any]) -> None:
    ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
    container_client.upload_blob(
        name=ledger_blob,
        data=json.dumps(ledger, indent=2, sort_keys=True).encode("utf-8"),
        overwrite=True,
        content_settings=content_settings("application/json"),
    )


def _generic_notice_projection_blob(name: str, prefix: str) -> bool:
    normalized_prefix = (prefix or "").strip("/")
    normalized = (name or "").strip("/")
    if normalized_prefix:
        return normalized.startswith(f"{normalized_prefix}/") and len(normalized) > len(normalized_prefix) + 1
    return bool(normalized)


def prune_stale_generic_notice_blobs(
    container_client,
    *,
    prefix: str,
    active_blob_names: set[str],
    files_ledger: dict[str, Any],
    dry_run: bool,
) -> int:
    """Remove stale flat generic notice blobs from prior selector versions."""
    if not active_blob_names:
        return 0

    stale = []
    for blob in container_client.list_blobs(name_starts_with=(prefix or "").strip("/")):
        name = str(getattr(blob, "name", "") or blob.get("name", ""))
        if _generic_notice_projection_blob(name, prefix) and name not in active_blob_names:
            stale.append(name)

    for name in stale:
        LOG.info("Deleting stale generic notice blob=%s", name)
        if not dry_run:
            container_client.delete_blob(name)
        files_ledger.pop(name, None)
    return len(stale)


def sync_generic_notices(
    *,
    graph: GraphClient,
    blob_service_client,
    config: SyncConfig,
) -> dict[str, int]:
    container_client = blob_service_client.get_container_client(config.destination_container)
    if not config.dry_run:
        try:
            container_client.create_container()
        except Exception as exc:
            error_code = getattr(exc, "error_code", "")
            if str(error_code).lower() != "containeralreadyexists":
                LOG.debug("Container create skipped or failed: %s", exc)

    ledger = load_ledger(container_client, config.ledger_blob)
    files_ledger: dict[str, Any] = ledger.setdefault("files", {})

    site_id = get_site_id(graph, config)
    drive_id = get_drive_id(graph, site_id, config.drive_name)
    case_folders = list_case_folders(graph, drive_id, config)

    stats = {
        "cases_seen": 0,
        "pdfs_seen": 0,
        "uploaded": 0,
        "skipped": 0,
        "failed": 0,
        "missing_notice_packet": 0,
        "stale_deleted": 0,
    }
    active_blob_names: set[str] = set()
    for case_folder in case_folders:
        case_name = str(case_folder.get("name") or "").strip()
        if not case_name:
            continue
        stats["cases_seen"] += 1
        pdfs = list_notice_pdfs(graph, drive_id, case_name, config)
        if not pdfs:
            stats["missing_notice_packet"] += 1
            continue
        for item in sorted(pdfs, key=lambda value: str(value.get("name", "")).lower()):
            stats["pdfs_seen"] += 1
            case_folder_id = str(case_folder.get("id") or "")
            source_item_id = str(item.get("id") or "")
            identity_source = case_folder_id or source_item_id
            blob_name = build_destination_blob_name(
                case_name,
                str(item.get("name", "")),
                config.destination_prefix,
                source_item_id=identity_source,
            )
            active_blob_names.add(blob_name)
            ledger_entry = files_ledger.get(blob_name)
            if not should_upload(item, ledger_entry):
                stats["skipped"] += 1
                continue
            LOG.info("Syncing generic notice case=%s file=%s blob=%s", case_name, item.get("name"), blob_name)
            if not config.dry_run:
                source_name = str(item.get("name", ""))
                try:
                    content = graph.download_file(
                        drive_id,
                        str(item["id"]),
                        as_pdf=not source_name.lower().endswith(".pdf"),
                    )
                    container_client.upload_blob(
                        name=blob_name,
                        data=io.BytesIO(content),
                        overwrite=True,
                        content_settings=content_settings("application/pdf"),
                        metadata={
                            "notice_source_type": "generic_notice",
                            "case_name": blob_metadata_value(case_name),
                            "case_slug": blob_metadata_value(slugify_case_name(case_name)),
                            "case_key": blob_metadata_value(
                                case_identity_key(case_name, source_item_id=identity_source)
                            ),
                            "original_file_name": blob_metadata_value(destination_pdf_name(source_name)),
                            "source_file_name": blob_metadata_value(source_name),
                            "sharepoint_item_id": blob_metadata_value(item.get("id", "")),
                            "sharepoint_case_folder_id": blob_metadata_value(case_folder_id),
                        },
                    )
                except requests.RequestException as exc:
                    stats["failed"] += 1
                    status = exc.response.status_code if exc.response is not None else "unknown"
                    LOG.warning(
                        "Generic notice download/upload failed case=%s file=%s status=%s",
                        case_name,
                        source_name,
                        status,
                    )
                    continue
            files_ledger[blob_name] = {
                "source": item_fingerprint(item),
                "case_name": case_name,
                "file_name": item.get("name"),
                "sharepoint_item_id": source_item_id,
                "sharepoint_case_folder_id": case_folder_id,
                "synced_at": datetime.now(timezone.utc).isoformat(),
            }
            stats["uploaded"] += 1

    if not config.dry_run:
        if stats["cases_seen"] > 0 and stats["pdfs_seen"] > 0:
            stats["stale_deleted"] = prune_stale_generic_notice_blobs(
                container_client,
                prefix=config.destination_prefix,
                active_blob_names=active_blob_names,
                files_ledger=files_ledger,
                dry_run=config.dry_run,
            )
        save_ledger(container_client, config.ledger_blob, ledger)
    return stats


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync generic SharePoint notice packet PDFs to Blob Storage")
    parser.add_argument("--dry-run", action="store_true", help="List changes without downloading or uploading")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    logging.getLogger("azure").setLevel(logging.WARNING)
    config = SyncConfig.from_env(dry_run=args.dry_run)
    stats = sync_generic_notices(
        graph=GraphClient.from_azure_identity(),
        blob_service_client=get_blob_service_client(),
        config=config,
    )
    LOG.info("Generic notice sync complete: %s", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
