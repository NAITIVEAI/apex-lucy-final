# AGENTS.md

## Mission

Complete the Lucy go-live refactor using a strict spec-driven workflow that is:
- research-backed where framework or SDK behavior may have changed
- minimal in scope
- one atomic unit at a time
- validated with tests before moving forward

This is a bounded implementation update, not a platform redesign.

---

## Required reading order at the start of every session

1. Read `/state/refactor-ledger.md`
2. Read `/TASKS.md`
3. Determine the current active plan:
   - use the plan already marked in progress, or
   - select the lowest-numbered incomplete plan in `/plans/`
4. Read **exactly one** active `/plans/*.md` file
5. Load and follow the skill:
   - `.agents/skills/lucy-spec-implementation/SKILL.md`

Do **not** read future plan files unless:
- the current plan is completed, or
- the current plan is explicitly blocked and the ledger has been updated

---

## Source of truth hierarchy

When instructions conflict, use this order:

1. Explicit user instruction in the current session
2. This `AGENTS.md`
3. `/TASKS.md`
4. The active `/plans/*.md` file
5. `.agents/skills/lucy-spec-implementation/SKILL.md`
6. Existing code patterns and typed constants already present in the repo

For implementation behavior, prefer:
- actual code
- actual schema/constants
- actual metadata
over transcript wording or guessed labels.

---

## Non-negotiable workflow

For **every** plan, follow this sequence:

1. Read the ledger
2. Read one active plan file
3. Inspect the codebase to identify:
   - exact execution path
   - relevant files
   - relevant helpers
   - relevant schema/field mappings
   - relevant tests
4. Dispatch subagents for read-heavy work
5. Gather proposed changes **before editing code**
6. Perform required research when the change touches evolving SDK/API/framework behavior
7. Compare code findings against research evidence
8. Make the smallest safe implementation
9. Run focused tests and scenario validation
10. Update `/state/refactor-ledger.md`
11. Only then proceed to the next plan

Never skip directly from reading a plan to editing code.

---

## Required subagent strategy

Use subagents liberally for analysis, but keep actual code edits tightly controlled.

### Minimum required subagents per plan
At minimum, use:

1. **Technical Project Manager / Coordinator**
   - summarize the active plan
   - restate acceptance criteria
   - track what remains
   - ensure scope control

2. **Technical Researcher**
   - required whenever the plan touches Azure AI Foundry, Azure AI Agents SDK, Responses API, tool behavior, package shape, SDK evolution, or any external framework/service that may have changed
   - gather current documentation
   - return citable evidence
   - identify whether proposed implementation is confirmed, ambiguous, or contradicted

3. **Code Mapper / Explorer**
   - inspect the repo
   - locate exact files, helpers, data mappings, and tests affected
   - propose minimal change points
   - do not edit code

4. **Principal Coding Agent**
   - review the exact implementation area
   - propose the minimal change
   - do not edit code until the controller has reviewed mapper + researcher findings

### Optional subagents
Use as needed:
- additional coding agent for isolated read-only review
- validator/tester
- schema-mapping reviewer
- diff reviewer

### Parallelism rules
Parallelize:
- code exploration
- schema discovery
- documentation research
- test discovery
- validation planning

Do **not** parallelize:
- write-heavy edits to the same files
- overlapping refactors in the same execution path
- multiple agents editing shared logic simultaneously

Read-heavy parallelism is good. Write-heavy swarm behavior is not.

---

## Required subagents for each active plan

Spawn these custom agents for every plan:

- `technical_pm`
- `code_mapper`
- `azure_docs_researcher` when the plan touches evolving external SDK/API/framework behavior
- `principal_coder` for implementation
- `validator` before marking the plan complete

For implementation-heavy plans, you may spawn two instances of `principal_coder` for proposal review, but do not allow multiple coding agents to edit the same execution path simultaneously.

---

## Research requirements

## Research is mandatory before code changes when:
- touching Azure AI Foundry behavior
- touching Azure AI Agents SDK behavior
- touching Responses API behavior
- touching tool orchestration behavior
- touching SDK/package usage that may have evolved
- touching external services/libraries/frameworks where behavior may have changed
- you are not certain the current implementation pattern is still correct

## Research is not mandatory when:
- the change is purely internal deterministic business logic
- the task is limited to local path logic
- the task is limited to local formatting/response construction
- the relevant schema/constants are fully discoverable in repo and no evolving framework behavior is involved

## Research quality bar
Prefer:
1. official vendor documentation
2. official SDK docs
3. official API references
4. primary-source release/migration docs

Return:
- exact feature or API researched
- what was confirmed
- what changed from older patterns
- what remains ambiguous
- citations or doc references sufficient for verification

Do not proceed on vague memory when the framework may have changed.

---

## Proposal-before-edit rule

Before making code changes, produce a short implementation brief containing:

- active plan file
- exact files likely to change
- exact helpers/functions/classes involved
- relevant schema/constants to use
- risk areas
- required research findings
- proposed minimal implementation approach
- test approach

Only edit code after this brief is grounded by:
- repo inspection
- required research
- acceptance criteria from the active plan

---

## Scope guardrails

The implementation scope is limited to the Lucy configuration update plans.

### In scope
- notice retrieval path standardization
- class member response construction using normalized fields
- historical / partial migration fallback behavior
- COA reason audit writeback for Lucy-driven address changes
- validation and regression checks for the above

### Explicitly out of scope
Do **not** implement or expand into:
- bank integrations
- return/bounce processing
- ACH ingestion
- wire ingestion
- nightly bank zip expansion
- Business Central activation
- model routing redesign
- Azure governance/dashboard/eval/red-team expansion
- broad anti-abuse/rate-limiting work
- CRM migration project
- generalized payout calculator
- Lucy architecture redesign
- unrelated cleanup refactors

Do not “improve adjacent things” just because they are nearby.

---

## Plan execution rules

Work exactly one atomic plan at a time.

The expected plan files are:

- `/plans/001-notice-path.md`
- `/plans/002-class-member-response.md`
- `/plans/003-historical-fallback.md`
- `/plans/004-coa-audit-writeback.md`
- `/plans/005-regression-validation.md`

### Plan progression rule
A plan is complete only when:
- implementation is finished
- tests relevant to that plan have been run
- results are recorded in the ledger
- blockers/follow-ups are recorded
- acceptance criteria are satisfied, or an explicit blocker is documented

Do not start the next plan until the current one is marked:
- completed, or
- blocked

---

## Coding rules

- Make the smallest safe implementation
- Prefer localized changes over broad refactors
- Prefer central helpers/constants/config over duplicated logic
- Preserve backward compatibility for historical Lucy records
- Do not invent fallback values
- Do not guess schema names when they can be confirmed
- Do not expose internal field names to end users
- Do not hardcode deprecated terminology when the backend provides the correct label
- Do not silently swallow important writeback failures

When a field/value is uncertain:
- inspect code/constants/metadata first
- research second if needed
- block and log if still unconfirmed

---

## Schema and field mapping rules

Transcript-derived names are not authoritative.

Before implementing field mappings, confirm actual schema names from:
- typed constants
- CRM metadata
- repo configuration
- existing integration code
- validated field references already in use

This is especially important for:
- normalized class count fields
- normalized PAGA fields
- estimated amount fields
- COA reason field
- any option-set / enum representation

If the API requires internal enum/option values, use those values rather than display text.

---

## Validation rules

For every plan, run the narrowest meaningful tests first, then scenario checks.

### Minimum validation standard
Validate:
- exact plan objective
- exact acceptance criteria
- relevant edge cases from the active plan
- no obvious regression in nearby flow

### Required scenario mindset
Test both:
- the happy path
- the realistic historical / incomplete-data path

### When validating
Prefer:
- existing test framework already used by the repo
- targeted integration tests
- targeted unit tests
- scenario checks aligned to the active plan

Do not invent a sprawling new test harness unless truly necessary.

---

## Failure handling and blockers

Stop and mark the plan blocked when:
- exact schema mapping cannot be confirmed safely
- required behavior is ambiguous in code and cannot be safely inferred
- external documentation contradicts the planned implementation
- SDK/framework behavior has changed in a way that invalidates the current path
- tests reveal a regression outside the plan’s safe scope
- a required dependency or environment condition is missing

When blocked:
1. do not continue speculative edits
2. update the ledger immediately
3. record:
   - plan name
   - blocker description
   - impact
   - exact missing information or decision needed

No fake certainty. No “should be fine.” That is how go-live turns into an expensive personality test.

---

## Ledger update requirement

After every completed or blocked plan, update:

`/state/refactor-ledger.md`

Include:
- plan file name
- status
- summary of what was done
- files changed
- research evidence used
- tests run
- results
- blockers
- follow-ups

The ledger must be detailed enough that a new session can resume without reconstructing context from scratch.

---

## Expected operating pattern per plan

Use this pattern every time:

### Step 1 — PM summary
- summarize active plan
- restate acceptance criteria
- identify exact completion bar

### Step 2 — Research + mapping
- researcher verifies current external behavior when required
- mapper locates exact code paths and schema touchpoints

### Step 3 — Proposed change review
- coding agent proposes minimal edits
- compare proposal against citations and repo reality

### Step 4 — Implementation
- make the smallest safe edit set
- keep changes bounded to the active plan

### Step 5 — Validation
- run targeted tests
- run scenario checks relevant to that plan

### Step 6 — Ledger
- record results in `/state/refactor-ledger.md`

### Step 7 — Progression
- move to next plan only after completion or explicit blocker logging

---

## Plan-specific reminders

### Plan 001 — Notice path
- standardize notice lookup to `Print/Notice packet`
- remove dependency on old `Mail Merge` assumptions
- avoid old `" - "` naming assumptions

### Plan 002 — Class member response
- use normalized field model
- render class count + metric naturally
- include estimated amount when available
- do not recompute payout logic unless existing implementation already requires it

### Plan 003 — Historical fallback
- missing normalized counts must not break user response
- estimated-amount-only fallback is correct behavior
- do not expose migration gaps to the user

### Plan 004 — COA audit writeback
- address changes via Lucy must also persist COA reason
- confirm exact field name and stored value before merge
- do not silently assume audit writeback succeeded

### Plan 005 — Regression validation
- validate the entire change set
- verify scope discipline
- confirm no bank-related work slipped in

---

## Definition of done

A plan is done when:
- the active plan’s objective is implemented
- the acceptance criteria are satisfied
- relevant tests pass
- edge cases in the plan are handled appropriately
- the ledger is updated
- no out-of-scope work was introduced

The overall implementation is done when:
- plans 001–005 are completed or explicitly resolved
- the release gate in the ledger is updated
- the result is ready, ready with low-risk follow-up, or blocked

---

## Final operating instruction

Be autonomous, but not improvisational.

Use judgment for:
- how to split read-heavy analysis
- which subagents to dispatch
- which tests to run first
- how to localize changes

Do **not** use judgment to:
- skip research when required
- skip the ledger
- skip tests
- broaden scope
- guess evolving SDK behavior
- guess schema names
- move to the next plan early
