# Refactor Ledger

This ledger records bounded Lucy refactor slices merged into `main`.

## COA Reason Writeback Slice — 2026-04-29

**Status:** implemented with schema ambiguity guard.

**Summary:**
- Added COA reason schema discovery around `new_classmembers` metadata.
- Lucy address updates now add `COA via Lucy` to the same Dynamics PATCH payload as the address fields.
- For Dataverse choice fields, Lucy resolves the stored integer option value from metadata instead of hardcoding a guessed value.
- Address updates now fail closed before PATCH when the COA reason field is missing, metadata is unavailable, or the `COA via Lucy` option cannot be confirmed.
- Live Dataverse metadata confirmed `new_classmembers` maps to logical entity `new_classmember`, `COA Reason` is `new_coareason` (`Picklist`), and `COA via Lucy` stores as `100000005`.
- Mirrored the behavior in the portal copy so the duplicate address-update surface does not drift.

**Files changed:**
- `agent/app/user_functions.py`
- `portal/app/user_functions.py`
- `agent/tests/test_coa_reason_writeback.py`

**Research evidence:**
- Microsoft Dataverse Web API docs confirm row updates use PATCH.
- Microsoft Dataverse choice docs confirm choice columns require stored numeric values rather than display labels.

**Tests run:**
- `python -m pytest -q agent/tests/test_coa_reason_writeback.py`
- `python -m py_compile agent/app/user_functions.py portal/app/user_functions.py agent/tests/test_coa_reason_writeback.py`
- Live Dataverse metadata query for `new_classmember.new_coareason`.

**Blockers / ambiguity:**
- No live writeback mutation was performed from this workspace.
