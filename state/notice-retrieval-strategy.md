# Notice Retrieval Strategy

Last updated: 2026-05-06

## Scope Decision

Lucy should use a tiered notice retrieval strategy:

1. Try individualized notice PDFs already copied into storage.
2. If no individualized notice is found, fall back to the generic,
   case-specific class action notice for the case.
3. In generic fallback mode, use the generic notice as the grounding source and
   enrich the answer with allowed member-specific Dynamics fields.

This preserves the value of the existing individualized notice corpus while
providing a targeted generic fallback path for cases where a member-specific
notice cannot be found.

## Business Rationale

- A large individualized PDF corpus already exists in storage. The Apr 17
  meeting context says ingestion had been paused, but the existing corpus should
  not be discarded.
- The agreed strategy is specific-first, generic-fallback, not generic-only.
- The Mar 26 meeting context standardized the generic notice path as
  `Print/Notice packet` under the case directory.
- The May 6 scope change explicitly retired the old "copy every class member
  Mail Merged PDF" sync strategy. The new sync job should copy only the generic
  case notice PDF(s) from `Print/Notice packet`.

## Functional Behavior

When a class member asks Lucy to explain their notice, case, or status:

1. Authenticate the member using the existing identity flow.
2. Resolve the authenticated member and case.
3. Attempt individualized notice lookup from the existing corpus using the
   existing mapping/search logic.
4. If found, use that individualized notice PDF as the primary grounding source.
5. If not found, retrieve the generic case notice from the standardized case
   path: `Print/Notice packet`.
6. Compose the response from grounded notice text plus allowed Dynamics member
   fields.

## Individualized Notice Mode

- Keep the existing individualized notice lookup path.
- Use the individualized PDF as the primary grounding source.
- Do not regress member-specific explanation from the actual notice content.
- Log the source type as `individual_notice`.

## Generic Notice Fallback Mode

- Use the generic notice at `case_root/Print/Notice packet`.
- If multiple notice PDFs exist in the source folder, select one stable generic
  source:
  - prefer a configured naming match when available,
  - otherwise use the first valid notice PDF by configured pattern.
- Explain the case/notice in simple language.
- Stay grounded in the generic notice text.
- Do not imply that an individualized notice was found.
- Enrich with allowed Dynamics fields when available, including:
  - estimated settlement amount,
  - member status context,
  - total class counts,
  - class count metric,
  - PAGA counts and metric if relevant,
  - other fields already allowed by Lucy's Dynamics access model.
- If normalized counts are missing, estimated-amount-only fallback is acceptable.
- Log the source type as `generic_notice_fallback`.

## Generic Notice Sync Job

- Source site: `https://apexclassaction.sharepoint.com/sites/ApexClassAction`.
- Source library/root:
  `/Shared Documents/Active Cases/Settlements/{case}/Print/Notice packet`.
- Copy PDFs only.
- Do not copy the old per-member `Print/Mail Merged` PDFs.
- Default destination is the single flat prefix
  `lucycmnotices/generic-notices/{case-slug}--{case-key}--{pdf}` because the
  current `lucy-notices-v2` Azure AI Search path watches `lucycmnotices` and
  should discover copied PDFs without changing Lucy's member-notice RAG
  pipeline.
- Do not create one virtual blob subfolder per case for the new projection.
  Keep generic templates in one targeted `generic-notices/` PDF corpus so
  Lucy can search only that small prefix when individualized lookup misses.
- Source path is `{case}/Print/Notice packet`. Historical cases that have not
  yet been moved into that standardized folder may fall back to a non-mail-merge
  notice file directly under `{case}/Print`.
- Keep a sync ledger keyed by destination blob and SharePoint item fingerprint
  (`id`, tags, size, modified time, and hashes when present) so unchanged
  notices are skipped and updated PDFs are overwritten.
- The existing blob indexer/vectorizer remains the ingestion path. Do not
  redesign RAG for this change.

## Guardrails

- Do not remove existing individualized notice code paths if they still work.
- Do not rely solely on generic notices when a specific notice is available.
- Do not fabricate individualized facts from generic notice text.
- Do not expose fields outside Lucy's approved Dynamics field policy.
- Do not perform dynamic payout math unless explicitly supported by the current
  field model and product behavior.

## Suggested Context Contract

Lucy orchestration should receive structured context equivalent to:

```json
{
  "notice_source_type": "individual_notice | generic_notice_fallback",
  "notice_document_text": "...",
  "member_context": {
    "estimated_amount": "...",
    "class_counts": "...",
    "class_count_metric": "...",
    "paga_counts": "...",
    "status_fields": "..."
  }
}
```

The prompt/orchestration layer should branch on `notice_source_type`:

- `individual_notice`: explain using the individualized notice.
- `generic_notice_fallback`: explain the case simply using the generic notice,
  then use Dynamics values for member-specific details.

## Observability

Track at minimum:

- individualized lookup success rate,
- generic fallback rate by case,
- missing generic notice rate,
- response source type,
- top failure reasons.

## Acceptance Criteria

1. Lucy attempts individualized notice retrieval before generic fallback.
2. If no individualized notice is found, Lucy falls back to
   `Print/Notice packet`.
3. In fallback mode, Lucy grounds the case explanation in the generic notice and
   enriches with allowed Dynamics member data.
4. The response path is logged for debugging and analytics.
5. Existing individualized notice behavior does not regress.
