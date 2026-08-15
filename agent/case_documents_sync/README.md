# Case Documents Sync

This container job mirrors the court/settlement documents that live in each
case's `Case Documents` folder from SharePoint into a dedicated Blob Storage
container consumed by the attorney portal. It never walks any other case
subfolder (`Print`, `Data Files`, `Disbursement`), so member-level material is
excluded at sync time rather than at portal request time.

Default source:

```text
https://apexclassaction.sharepoint.com/sites/ApexClassAction
/Shared Documents/Active Cases/Settlements/{case}/Case Documents
```

Default destination:

```text
portal-case-documents/{case-folder-name}/{file-name}
```

The destination container is deliberately NOT `lucycmnotices`: the
`lucy-notices-v2` Azure AI Search indexers watch that container at root level,
and mirrored court documents must not enter Lucy's RAG corpus.

Files are mirrored verbatim (no PDF conversion, no renaming) so the portal can
resolve a case's Dataverse `new_foldername` against blob prefixes, including
its punctuation-normalized fallback for drifted folder names. Only `.pdf`,
`.doc`, and `.docx` files are copied, and file names containing mail-merge/SSN
terms are excluded as defense in depth.

A JSON ledger records a per-file fingerprint so unchanged files are skipped on
subsequent runs, and mirrored blobs whose SharePoint source disappeared or was
renamed are pruned.

Required identity: Microsoft Graph read access to the SharePoint site and Blob
Storage write access to the destination container (same shape as
`generic_notice_sync`).

Typical build context:

```bash
docker build -f case_documents_sync/Dockerfile -t case-documents-sync .
```

Run:

```bash
python -m case_documents_sync.sync [--dry-run]
```

Useful environment variables:

- `SHAREPOINT_SITE_HOST`
- `SHAREPOINT_SITE_PATH`
- `SHAREPOINT_DRIVE_NAME`
- `SHAREPOINT_CASE_ROOT`
- `CASE_DOCUMENTS_SUBPATH`
- `AZURE_CASE_DOCUMENTS_CONTAINER`
- `CASE_DOCUMENTS_LEDGER_BLOB`
- `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`
- `AZURE_STORAGE_ACCOUNT_NAME` or `AZURE_STORAGE_CONNECTION_STRING`
