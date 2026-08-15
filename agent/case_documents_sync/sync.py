"""Mirror per-case Case Documents folders from SharePoint to Azure Blob Storage.

This job copies every eligible court/settlement document under
``{case}/Case Documents`` into a dedicated container consumed by the attorney
portal. It intentionally never walks any other case subfolder (``Print``,
``Data Files``, ``Disbursement``) so member-level material can never reach the
portal-readable container. Files are mirrored verbatim under their SharePoint
folder and file names; the portal resolves case-to-folder naming drift on its
side at request time.
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import quote

import requests


LOG = logging.getLogger("case_documents_sync")

DEFAULT_SITE_HOST = "apexclassaction.sharepoint.com"
DEFAULT_SITE_PATH = "/sites/ApexClassAction"
DEFAULT_CASE_ROOT = "/Shared Documents/Active Cases/Settlements"
DEFAULT_DRIVE_NAME = "Documents"
DEFAULT_DOCUMENTS_SUBPATH = "Case Documents"
DEFAULT_DESTINATION_CONTAINER = "portal-case-documents"
DEFAULT_LEDGER_BLOB = "_sync/case_documents_ledger.json"
LEDGER_PREFIX = "_sync/"
ALLOWED_EXTENSIONS = (".pdf", ".doc", ".docx")
EXCLUDED_SOURCE_NAME_TERMS = ("mail merge", "for merge", "with ssn", "ssn")
CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@dataclass(frozen=True)
class SyncConfig:
    site_host: str = DEFAULT_SITE_HOST
    site_path: str = DEFAULT_SITE_PATH
    drive_name: str = DEFAULT_DRIVE_NAME
    case_root_path: str = DEFAULT_CASE_ROOT
    documents_subpath: str = DEFAULT_DOCUMENTS_SUBPATH
    destination_container: str = DEFAULT_DESTINATION_CONTAINER
    ledger_blob: str = DEFAULT_LEDGER_BLOB
    dry_run: bool = False

    @classmethod
    def from_env(cls, *, dry_run: bool = False) -> "SyncConfig":
        return cls(
            site_host=os.getenv("SHAREPOINT_SITE_HOST", DEFAULT_SITE_HOST),
            site_path=os.getenv("SHAREPOINT_SITE_PATH", DEFAULT_SITE_PATH),
            drive_name=os.getenv("SHAREPOINT_DRIVE_NAME", DEFAULT_DRIVE_NAME),
            case_root_path=os.getenv("SHAREPOINT_CASE_ROOT", DEFAULT_CASE_ROOT),
            documents_subpath=os.getenv("CASE_DOCUMENTS_SUBPATH", DEFAULT_DOCUMENTS_SUBPATH),
            destination_container=os.getenv(
                "AZURE_CASE_DOCUMENTS_CONTAINER", DEFAULT_DESTINATION_CONTAINER
            ),
            ledger_blob=os.getenv("CASE_DOCUMENTS_LEDGER_BLOB", DEFAULT_LEDGER_BLOB),
            dry_run=dry_run,
        )


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


def build_case_documents_path(case_name: str, config: SyncConfig) -> str:
    root = normalize_drive_relative_path(config.case_root_path, config.drive_name)
    suffix = config.documents_subpath.strip("/")
    return "/".join(part for part in (root, case_name, suffix) if part)


def build_destination_blob_name(case_folder_name: str, file_name: str) -> str:
    folder = (case_folder_name or "").strip().strip("/")
    file_part = (file_name or "").strip().strip("/")
    return f"{folder}/{file_part}"


def blob_content_type(file_name: str) -> str:
    lowered = (file_name or "").lower()
    for extension, content_type in CONTENT_TYPES.items():
        if lowered.endswith(extension):
            return content_type
    return "application/octet-stream"


def is_eligible_case_document(file_name: str) -> bool:
    lowered = (file_name or "").lower()
    if any(term in lowered for term in EXCLUDED_SOURCE_NAME_TERMS):
        return False
    return lowered.endswith(ALLOWED_EXTENSIONS)


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

    def download_file(self, drive_id: str, item_id: str) -> bytes:
        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content"
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


def list_case_documents(
    graph: GraphClient,
    drive_id: str,
    case_folder_name: str,
    config: SyncConfig,
) -> list[dict[str, Any]]:
    documents_path = build_case_documents_path(case_folder_name, config)
    try:
        children = graph.get_all(graph_path_children_url(drive_id, documents_path))
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        LOG.debug("No Case Documents folder for case=%s status=%s", case_folder_name, status)
        return []
    return [
        item
        for item in children
        if "file" in item and is_eligible_case_document(str(item.get("name", "")))
    ]


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


def is_mirror_blob(name: str) -> bool:
    normalized = (name or "").strip("/")
    if not normalized or normalized.startswith(LEDGER_PREFIX):
        return False
    return "/" in normalized


def prune_stale_case_document_blobs(
    container_client,
    *,
    active_blob_names: set[str],
    files_ledger: dict[str, Any],
    dry_run: bool,
) -> int:
    """Remove mirrored blobs whose SharePoint source was renamed or deleted."""
    if not active_blob_names:
        return 0

    stale = []
    for blob in container_client.list_blobs():
        name = str(getattr(blob, "name", "") or blob.get("name", ""))
        if is_mirror_blob(name) and name not in active_blob_names:
            stale.append(name)

    for name in stale:
        LOG.info("Deleting stale case document blob=%s", name)
        if not dry_run:
            container_client.delete_blob(name)
        files_ledger.pop(name, None)
    return len(stale)


def sync_case_documents(
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
        "files_seen": 0,
        "uploaded": 0,
        "skipped": 0,
        "failed": 0,
        "missing_case_documents": 0,
        "stale_deleted": 0,
    }
    active_blob_names: set[str] = set()
    for case_folder in case_folders:
        case_name = str(case_folder.get("name") or "").strip()
        if not case_name:
            continue
        stats["cases_seen"] += 1
        documents = list_case_documents(graph, drive_id, case_name, config)
        if not documents:
            stats["missing_case_documents"] += 1
            continue
        for item in sorted(documents, key=lambda value: str(value.get("name", "")).lower()):
            stats["files_seen"] += 1
            source_name = str(item.get("name", ""))
            blob_name = build_destination_blob_name(case_name, source_name)
            active_blob_names.add(blob_name)
            ledger_entry = files_ledger.get(blob_name)
            if not should_upload(item, ledger_entry):
                stats["skipped"] += 1
                continue
            LOG.info("Syncing case document case=%s file=%s", case_name, source_name)
            if not config.dry_run:
                try:
                    content = graph.download_file(drive_id, str(item["id"]))
                    container_client.upload_blob(
                        name=blob_name,
                        data=io.BytesIO(content),
                        overwrite=True,
                        content_settings=content_settings(blob_content_type(source_name)),
                        metadata={
                            "source_file_name": source_name.encode("ascii", "ignore").decode("ascii")[:1024],
                            "sharepoint_item_id": str(item.get("id", "")),
                            "sharepoint_case_folder_id": str(case_folder.get("id", "")),
                            "last_modified": str(item.get("lastModifiedDateTime", "")),
                        },
                    )
                except requests.RequestException as exc:
                    stats["failed"] += 1
                    status = exc.response.status_code if exc.response is not None else "unknown"
                    LOG.warning(
                        "Case document download/upload failed case=%s file=%s status=%s",
                        case_name,
                        source_name,
                        status,
                    )
                    continue
            files_ledger[blob_name] = {
                "source": item_fingerprint(item),
                "case_name": case_name,
                "file_name": source_name,
                "synced_at": datetime.now(timezone.utc).isoformat(),
            }
            stats["uploaded"] += 1

    if not config.dry_run:
        if stats["cases_seen"] > 0 and stats["files_seen"] > 0:
            stats["stale_deleted"] = prune_stale_case_document_blobs(
                container_client,
                active_blob_names=active_blob_names,
                files_ledger=files_ledger,
                dry_run=config.dry_run,
            )
        save_ledger(container_client, config.ledger_blob, ledger)
    return stats


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mirror per-case SharePoint Case Documents folders to Blob Storage"
    )
    parser.add_argument("--dry-run", action="store_true", help="List changes without downloading or uploading")
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    logging.getLogger("azure").setLevel(logging.WARNING)
    config = SyncConfig.from_env(dry_run=args.dry_run)
    stats = sync_case_documents(
        graph=GraphClient.from_azure_identity(),
        blob_service_client=get_blob_service_client(),
        config=config,
    )
    LOG.info("Case documents sync complete: %s", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
