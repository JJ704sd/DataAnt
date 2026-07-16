# Excel Candidate Review Workflow Design

## Objective

Extend the current controlled Douban movie demo with an auditable human-review
loop for ambiguous search results. The existing `movies` worksheet remains the
authoritative 12-column result table. A second `review_queue` worksheet records
candidate snapshots and human decisions, and a new explicit `apply-review`
command validates the complete pending batch before performing any live access.

The design targets the largest observed quality gap in the current controlled
workbook: most rows are `REVIEW_REQUIRED`, while deterministic matching, live-run
authorization, resume behavior, offline CI, and site-protection stopping rules
are already implemented.

## Confirmed baseline

The design is based on `main` at commit `3299ce3`:

- the complete offline suite passes with 164 tests;
- live commands require `--live-approved`, `--max-queries 1..10`, headed mode,
  and `--min-interval >= 5`;
- the runner stops on `BLOCKED` and `SITE_PROTECTION_CHALLENGE`;
- `movies` uses a fixed 12-column schema and `task_id` upserts;
- deterministic matching supports normalized exact title, title plus year, and
  unique primary-title-prefix plus year;
- a controlled 10-row workbook passes the workbook verifier, with the observed
  distribution `SUCCESS=1`, `REVIEW_REQUIRED=6`, and `UNEXPECTED_ERROR=3`;
- an older MiniMax candidate-matcher plan exists, but no LLM package, matcher
  module, CLI switch, or runner integration is implemented on `main`.

This round does not increase the live batch ceiling. It improves decision quality
and recovery at the existing controlled scale.

## Selected approach

Use one workbook with two worksheets:

1. `movies` remains the machine-owned result table.
2. `review_queue` is the human-review interface and audit record.

This is preferred over a separate CSV because reviewers can see the result and
candidate evidence in one artifact. It is preferred over a local web application
because the current product is CLI- and workbook-oriented, and a web stack would
add deployment, state synchronization, and security scope without improving the
core decision contract.

Review application is an explicit `apply-review` command. A normal `run` never
silently consumes human edits.

## Workbook contract

### `movies`

The existing worksheet name and 12 columns remain unchanged:

```text
task_id
query
query_year
matched_title
matched_year
director
rating
detail_url
match_method
status
error_message
collected_at
```

Existing callers and `verify_controlled_workbook()` therefore remain compatible.

### `review_queue`

Each ambiguous task occupies one row. Candidates are stored as a bounded snapshot
of at most five items so later site changes do not alter what the reviewer saw.

Machine-owned identity and evidence columns:

```text
review_id
task_id
query
query_year
candidate_count
candidate_1_title
candidate_1_year
candidate_1_kind
candidate_1_url
...
candidate_5_title
candidate_5_year
candidate_5_kind
candidate_5_url
created_at
```

Human-editable decision columns:

```text
decision_type
selected_candidate
manual_detail_url
review_note
```

Machine-owned application columns:

```text
apply_status
applied_url
applied_at
apply_error
```

`decision_type` accepts exactly:

- `CANDIDATE`: use one captured candidate; `selected_candidate` must be an
  integer from 1 through `candidate_count`, and `manual_detail_url` must be
  empty.
- `MANUAL_URL`: use a reviewer-supplied canonical Douban movie detail URL;
  `manual_detail_url` is required and `selected_candidate` must be empty.
- `SKIP`: confirm that the item should remain unresolved; both selection fields
  must be empty.

`review_note` is optional and limited to a safe, bounded text length. It is an
operator note only and is never sent to Douban or an LLM.

### Stable identity and replacement

`review_id` is deterministically derived from the task identity and the candidate
snapshot. A repeated normal run with the same unresolved evidence updates the
same open review row instead of appending duplicates. If the candidate snapshot
changes before a decision is applied, the old row is marked superseded and a new
review row is created. Human decisions are never silently carried to materially
different candidate evidence.

Successfully applied rows are immutable audit records. A later ambiguity for the
same task receives a new `review_id`.

## Normal `run` behavior

The existing deterministic matcher keeps priority. When it cannot choose a unique
candidate:

1. write or update the `movies` row as `REVIEW_REQUIRED`;
2. write the bounded candidate snapshot to `review_queue`;
3. leave all human-editable decision fields empty for a new review;
4. preserve an already-entered decision only when the `review_id` and candidate
   snapshot are unchanged;
5. continue the controlled batch under the existing interval and stopping rules.

No detail page is opened for an unresolved candidate. Candidate snapshots contain
only public search-result metadata already used by the matcher.

If there are no candidates, the result remains `NOT_FOUND` and no review row is
created.

## `apply-review` command

The command shape is:

```powershell
python -m app.main apply-review `
  --workbook .\outputs\douban_movies.xlsx `
  --live-approved `
  --max-queries 5 `
  --headed `
  --min-interval 5 `
  --profile-dir .\browser-profile\douban
```

It has two separate phases.

### Phase 1: complete offline preflight

Before constructing `BrowserSession`, creating a profile, modifying the workbook,
or accessing the network, the command:

1. opens and validates both worksheets;
2. selects rows that are pending human application;
3. validates every pending row;
4. detects duplicated or conflicting decisions for the same `task_id`;
5. verifies that the referenced `movies` row exists and is still eligible for
   review;
6. validates candidate indexes against the immutable snapshot;
7. validates manual URLs;
8. checks that the number of live decisions does not exceed
   `--max-queries`;
9. converts valid rows into an immutable in-memory execution plan.

If any pending row is incomplete or invalid, the whole command returns exit code
2. It reports all validation errors with row numbers and `review_id` values, does
not launch a browser, and does not change either worksheet.

`SKIP` rows participate in validation but do not count as live queries.

### Manual URL validation

A manual URL is accepted only when:

- its scheme is `https`;
- its hostname is exactly `movie.douban.com`;
- its path is exactly `/subject/<digits>/`, allowing normalization of a missing
  trailing slash;
- it contains no username, password, fragment, or unexpected port;
- it has no query parameters;
- it does not conflict with a different decision for the same task;
- it is not reused by another pending task in the same application batch unless
  that reuse is explicitly the same `task_id`.

The preflight stores only the normalized URL in the execution plan.

### Phase 2: controlled application

Only after preflight succeeds does the command validate and apply the standard
live-run gate. It then:

1. marks `SKIP` rows as acknowledged without live access while leaving the
   corresponding `movies` row at `REVIEW_REQUIRED`;
2. resolves `CANDIDATE` rows to the selected captured URL;
3. resolves `MANUAL_URL` rows to the normalized manual URL;
4. fetches and parses each selected detail page with the existing Douban adapter;
5. updates the existing `movies` row rather than appending a new result;
6. records the final URL, application status, timestamp, and bounded error text
   in `review_queue`;
7. saves both worksheet updates through the existing temporary-file and atomic
   replacement strategy.

Human review is authoritative for candidate selection, so a successfully applied
row uses a new match method `HUMAN_REVIEW`. The detail parser remains
authoritative for extracted title, year, director, rating, canonical URL, and
success status.

## Failure and retry semantics

The command preserves current site and safety behavior:

- `BLOCKED` and `SITE_PROTECTION_CHALLENGE` update the current review attempt,
  persist the corresponding `movies` status, and stop the remaining batch;
- CAPTCHA, login security checks, rate limiting, and `sec.douban.com` are never
  bypassed;
- `NETWORK_ERROR` uses only the existing bounded retry behavior;
- `PAGE_CHANGED` records the failure and leaves the review row retryable after an
  offline parser repair;
- `OUTPUT_LOCKED` returns exit code 4 and must not corrupt the previous workbook;
- unexpected global browser failures return exit code 5;
- validation and configuration errors return exit code 2 before live access.

`apply-review` never accepts `--retry-status BLOCKED` or
`--retry-status SITE_PROTECTION_CHALLENGE`.

Re-running `apply-review` skips rows with `apply_status=APPLIED` or
`apply_status=SKIPPED`. Failed rows remain retryable only when their decision and
candidate snapshot are unchanged. Editing an already applied machine-owned cell
is treated as workbook corruption, not as a request to reapply.

## Component boundaries

### `app/models.py`

Add focused immutable types for candidate snapshots, review decisions, validated
review actions, and review application states. Add `HUMAN_REVIEW` to
`MatchMethod`.

### `app/excel_store.py`

Keep the existing `movies` behavior and add workbook-level operations for
creating, reading, upserting, and atomically updating `review_queue`. Schema
validation for the two worksheets stays at the persistence boundary.

### `app/review_service.py`

Own all offline interpretation and validation of human-edited review rows. Its
output is an immutable execution plan. It has no browser, network, logging, or
filesystem-write responsibility.

### `app/review_runner.py`

Execute only validated actions. It coordinates detail fetches, result updates,
review audit updates, interval enforcement, and stop conditions. It does not
re-interpret workbook cells.

### `app/runner.py`

When deterministic matching returns no decision, create or update the candidate
snapshot through the store. Existing deterministic success paths remain
unchanged.

### `app/main.py`

Add `apply-review`, perform offline workbook preflight before browser
construction, enforce the same live authorization gate, and map known failures to
the existing exit-code scheme.

## Data integrity and auditability

- `movies` stays authoritative for the latest task outcome.
- `review_queue` stays authoritative for what evidence the human reviewed and
  what decision was applied.
- Machine-owned review columns are protected by validation rather than relying
  on Excel worksheet protection.
- A single atomic workbook replacement commits the paired `movies` and
  `review_queue` changes.
- Candidate snapshots and notes are stored only in the ignored runtime workbook,
  never in Git.
- Logs contain `review_id`, `task_id`, stage, status, and elapsed time, but no
  Cookie, browser profile, full HTML, or sensitive request metadata.

## Forward compatibility: automated batches and recovery

The next planned capability after the human-review loop is automated batch
execution and recovery. This design must therefore leave stable seams for a
future batch coordinator without turning the current Douban workflow into an
unattended crawler.

The current implementation plan will preserve the following boundaries:

- review validation produces an immutable execution plan with stable action
  identities;
- each applied action has an explicit lifecycle state rather than relying only
  on row position;
- persistence can checkpoint one completed action at a time through atomic
  workbook replacement;
- runners accept an already validated collection of actions and return a
  structured summary of processed, skipped, retryable, and stopped work;
- retry eligibility is derived from recorded status and an explicit policy;
- repeated invocation is safe and skips terminal actions;
- stop reasons distinguish operator-correctable input, transient technical
  failure, output locking, page change, hard blocking, and site-protection
  challenge;
- live authorization remains a CLI boundary and is not embedded in a saved plan,
  workbook, scheduled task, or reusable credential.

For Douban, “automated batch” means an operator starts each controlled invocation
with `--live-approved`, `--max-queries N` where `1 <= N <= 10`, headed mode, and
an interval of at least five seconds. Within that invocation the program may
checkpoint progress, skip completed actions, and resume retryable actions.
It must not automatically launch the next live batch, schedule a later retry,
wait through a site-protection window, or reuse prior approval.

A later generic batch layer may provide:

- a durable `batch_id` and run manifest;
- `plan`, `run`, `status`, and `resume` commands;
- per-action attempt history and aggregate progress;
- dry-run validation and estimated live-query counts;
- explicit retry policies for transient statuses;
- machine-readable JSON summaries alongside the human workbook;
- pluggable execution backends for data sources whose authorization permits
  unattended operation.

Those capabilities are not implemented in this round. The review workflow only
establishes the state model and idempotent execution contract they will consume.

## Testing strategy

Implementation follows test-driven development.

### Pure validation tests

Cover:

- every legal decision type;
- blank and unknown decision values;
- candidate indexes that are non-numeric, zero, negative, or beyond the snapshot;
- mutually conflicting candidate and manual URL fields;
- accepted canonical URL and normalized missing trailing slash;
- rejected scheme, host, port, credentials, query, fragment, and path;
- duplicate task decisions and duplicate manual URLs;
- missing or stale `movies` task references;
- mixed valid and invalid rows proving whole-batch rejection;
- live-decision counting excluding `SKIP`;
- immutable execution-plan output.

### Workbook tests

Cover:

- creation of both schemas;
- preservation of the original 12-column `movies` contract;
- candidate snapshot upsert without duplicate open rows;
- superseding changed snapshots;
- preservation of human fields for unchanged snapshots;
- paired worksheet atomic save;
- workbook locking;
- corrupted machine-owned fields;
- idempotent reapplication of completed rows.

### Runner and CLI tests

Cover:

- ambiguous normal runs create review rows;
- deterministic matches do not create review rows;
- `NOT_FOUND` does not create review rows;
- preflight failure never constructs a browser or changes a workbook;
- missing live authorization, excess query count, headless mode, and short
  interval fail before browser construction;
- candidate and manual URL actions fetch the intended detail page;
- `SKIP` performs no network access;
- successful application updates both worksheets and uses `HUMAN_REVIEW`;
- site protection stops the remaining application batch;
- network, page-change, locked-output, and unexpected-error mappings;
- repeated commands skip already applied rows.

The full offline suite and portable core coverage gate must remain green. Offline
CI must not invoke `apply-review` with live authorization or access Douban.

## Documentation changes

The implementation round will update the README with:

- the two-worksheet workflow;
- editable versus machine-owned columns;
- a copyable `apply-review` command;
- validation-error examples;
- retry and stop rules;
- a reminder to close Excel before applying;
- the prohibition on committing workbooks, profiles, HTML, screenshots, logs,
  and other runtime evidence.

## Non-goals

This round does not:

- build a web review interface;
- automate login, CAPTCHA solving, or site-protection challenges;
- increase the ten-query live ceiling;
- schedule unattended live jobs or automatically chain Douban batches;
- add a second site adapter;
- allow arbitrary non-Douban URLs;
- change the 12-column `movies` schema;
- automatically apply decisions during a normal `run`;
- implement MiniMax in the same implementation plan.

MiniMax remains a later, independently optional enhancement. The human-review
contract should be completed and measured first; an LLM may later propose a
decision, but it must not bypass the same validation or live-application gates.

## Acceptance criteria

- An ambiguous task produces one open `review_queue` row with at most five
  candidate snapshots.
- A reviewer can select a captured candidate, enter a valid manual Douban detail
  URL, or explicitly skip the task.
- One invalid pending row rejects the complete batch before browser construction
  and without workbook mutation.
- A valid `apply-review` batch obeys all existing live-run limits and stopping
  rules.
- Successful application updates the original `movies` row and records an
  auditable review outcome in the same atomic workbook save.
- Re-running the command does not reapply completed decisions.
- The original workbook verifier remains compatible with the `movies` worksheet.
- All offline tests and release gates remain network-free and pass.
- No runtime workbook, browser profile, diagnostic artifact, Cookie, or secret is
  added to Git.
