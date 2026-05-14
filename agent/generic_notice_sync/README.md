# Generic Notice Sync

This container job copies only generic, case-specific notice packet PDFs from
SharePoint into Blob Storage. It does not copy individualized class member mail
merge notices.

Default source:

```text
https://apexclassaction.sharepoint.com/sites/ApexClassAction
/Shared Documents/Active Cases/Settlements/{case}/Print/Notice packet
```

Default destination:

```text
lucycmnotices/generic-notices/{case-slug}--{case-key}--{pdf-name}
```

The `lucycmnotices` default is deliberate: the current `lucy-notices-v2`
Azure AI Search indexers already watch that container hourly. The sync job does
not create or route Search indexers; copied PDFs are discovered by the existing
root-level indexing path.

Generic notices are written as a flat single-prefix corpus under
`generic-notices/`, not as one virtual subfolder per case. This keeps Lucy's
generic fallback search targeted at one small PDF corpus while avoiding broad
listing or discovery across the member-specific notice corpus.

The source contract is `{case}/Print/Notice packet`. For historical cases that
have not yet been moved into that folder, the sync job falls back to a notice
file directly under `{case}/Print` and still excludes mail-merge/SSN files.

Required app permissions depend on the identity used for Graph access, but the
job expects Microsoft Graph read access to the SharePoint site and Blob Storage
write access to the destination container.

Typical build context:

```bash
docker build -f generic_notice_sync/Dockerfile -t generic-notice-sync .
```

Run:

```bash
python -m generic_notice_sync.sync
```

Useful environment variables:

- `SHAREPOINT_SITE_HOST`
- `SHAREPOINT_SITE_PATH`
- `SHAREPOINT_DRIVE_NAME`
- `SHAREPOINT_CASE_ROOT`
- `GENERIC_NOTICE_SUBPATH`
- `AZURE_GENERIC_NOTICE_CONTAINER`
- `GENERIC_NOTICE_BLOB_PREFIX`
- `GENERIC_NOTICE_LEDGER_BLOB`
- `GRAPH_TENANT_ID`, `GRAPH_CLIENT_ID`, `GRAPH_CLIENT_SECRET`
- `AZURE_STORAGE_ACCOUNT_NAME` or `AZURE_STORAGE_CONNECTION_STRING`
