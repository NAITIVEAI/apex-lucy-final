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
lucycmnotices/generic-notices/{case-slug}/{pdf-name}
```

The `lucycmnotices` default is deliberate: the current `lucy-notices-v2`
Azure AI Search indexers already watch that container hourly.

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
