"""Lucy field policy derived from the COO-approved Dataverse form tab.

Source of truth:
- Table: new_classmember
- Main form: Information
- Form ID: 05e90c7f-deeb-4e50-b9c0-f7bf207bb3a2
- Tab: Lucy Class Member Data

The policy separates fields Lucy may reason about from internal IDs needed to
join Dataverse records. Internal IDs are tool plumbing, not user-facing context.
"""

from __future__ import annotations

from typing import Iterable


LUCY_CLASS_MEMBER_FORM_ID = "05e90c7f-deeb-4e50-b9c0-f7bf207bb3a2"
LUCY_CLASS_MEMBER_FORM_TAB = "Lucy Class Member Data"

CLASS_MEMBER_ENTITY_SET = "new_classmembers"
MEMBER_DISBURSEMENT_ENTITY_SET = "new_memberdisbursements"

CLASS_MEMBER_INTERNAL_FIELDS = (
    "new_classmemberid",
    "_new_case_value",
)

MEMBER_DISBURSEMENT_INTERNAL_FIELDS = (
    "new_memberdisbursementid",
    "_new_classmember_value",
)

LUCY_AUTH_FIELDS = (
    "new_apexid",
    "new_fullname",
    "new_firstname",
    "new_lastname",
    "new_shortsocial",
)

LUCY_CONTACT_FIELDS = (
    "new_coareason",
    "new_address",
    "new_city",
    "new_state",
    "new_zip",
    "new_email",
    "new_phonenumber",
    "new_pinnumber",
    "new_employeeid",
    "new_settlementwebsitecm",
)

LUCY_SETTLEMENT_FIELDS = (
    "new_estimatedsettlementamount",
    "new_classworkweeks",
    "new_pagaweeks",
)

LUCY_EMPLOYMENT_FIELDS = (
    "new_hiredate",
    "new_termdate",
    "new_rehiredate",
    "new_secondtermdate",
    "new_wagestatements",
    "new_totalearnings",
)

LUCY_POTENTIAL_MEMBER_STATUS_FIELDS = (
    "_new_projectcoordinator_value",
    "new_potentialclassmemberstatus",
    "new_counseloutreachdate",
    "new_followupdate1",
    "new_followupdate2",
    "new_followupdate3",
    "new_followupdate4",
)

NOTICE_TEMPLATE_SCHEMA_MAP = {
    "estimated_settlement_amount": {
        "d365_entity": CLASS_MEMBER_ENTITY_SET,
        "d365_field": "new_estimatedsettlementamount",
        "label": "Estimated settlement amount",
    },
    "class_count": {
        "d365_entity": CLASS_MEMBER_ENTITY_SET,
        "d365_field": "new_classworkweeks",
        "label": "Class count",
    },
    "paga_count": {
        "d365_entity": CLASS_MEMBER_ENTITY_SET,
        "d365_field": "new_pagaweeks",
        "label": "PAGA count",
    },
}

LUCY_MEMBER_DISBURSEMENT_FIELDS = (
    "new_checkamount",
    "new_checknumbertop",
    "new_checkcashed",
    "new_checkdate",
    "new_checkvoiddate",
    "cr7fe_bankaccountnumber",
    "new_disbursementnumber",
    "new_case",
    "createdon",
    "modifiedby",
    "cr7fe_postalsort",
    "cr7fe_traypc",
    "cr7fe_mailbarcode",
    "new_casedisbursement",
)

LUCY_CLASS_MEMBER_READ_FIELDS_BY_OUTCOME = {
    "auth": LUCY_AUTH_FIELDS,
    "contact": LUCY_AUTH_FIELDS + LUCY_CONTACT_FIELDS,
    "settlement": LUCY_AUTH_FIELDS + LUCY_SETTLEMENT_FIELDS,
    "employment": LUCY_AUTH_FIELDS + LUCY_EMPLOYMENT_FIELDS,
    "earnings": LUCY_AUTH_FIELDS + LUCY_EMPLOYMENT_FIELDS,
    "status": LUCY_AUTH_FIELDS + LUCY_SETTLEMENT_FIELDS + LUCY_POTENTIAL_MEMBER_STATUS_FIELDS,
    "timeline": LUCY_AUTH_FIELDS + LUCY_EMPLOYMENT_FIELDS + LUCY_POTENTIAL_MEMBER_STATUS_FIELDS,
    "disbursements": LUCY_AUTH_FIELDS,
    "all": (
        LUCY_AUTH_FIELDS
        + LUCY_CONTACT_FIELDS
        + LUCY_SETTLEMENT_FIELDS
        + LUCY_EMPLOYMENT_FIELDS
        + LUCY_POTENTIAL_MEMBER_STATUS_FIELDS
    ),
}

LUCY_CLASS_MEMBER_UPDATE_FIELDS = (
    "new_address",
    "new_city",
    "new_state",
    "new_zip",
)

LUCY_SYSTEM_WRITE_FIELDS = (
    "new_coareason",
)


def _dedupe(fields: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for field in fields:
        if field and field not in seen:
            seen.add(field)
            ordered.append(field)
    return tuple(ordered)


def class_member_fields_for_outcome(
    outcome: str = "all",
    *,
    include_internal: bool = False,
) -> tuple[str, ...]:
    fields = LUCY_CLASS_MEMBER_READ_FIELDS_BY_OUTCOME.get(
        (outcome or "all").lower(),
        LUCY_CLASS_MEMBER_READ_FIELDS_BY_OUTCOME["all"],
    )
    if include_internal:
        fields = CLASS_MEMBER_INTERNAL_FIELDS + fields
    return _dedupe(fields)


def member_disbursement_fields(*, include_internal: bool = False) -> tuple[str, ...]:
    fields = LUCY_MEMBER_DISBURSEMENT_FIELDS
    if include_internal:
        fields = MEMBER_DISBURSEMENT_INTERNAL_FIELDS + fields
    return _dedupe(fields)


def select_clause(fields: Iterable[str]) -> str:
    return ",".join(_dedupe(fields))


def restrict_fields(requested_fields: str | None, allowed_fields: Iterable[str]) -> tuple[str, ...]:
    allowed = set(allowed_fields)
    if not requested_fields:
        return _dedupe(allowed_fields)
    requested = [field.strip() for field in requested_fields.split(",") if field.strip()]
    return _dedupe(field for field in requested if field in allowed)


def filter_record(record: dict, allowed_fields: Iterable[str]) -> dict:
    allowed = set(allowed_fields)
    return {key: value for key, value in record.items() if key in allowed or key.startswith("@")}
