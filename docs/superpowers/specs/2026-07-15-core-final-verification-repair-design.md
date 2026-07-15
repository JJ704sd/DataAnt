# Core Final Verification Repair Design

## Objective

Restore the Core 12 release gate with the smallest safe change, then document the
next Core stabilization phase and the Git workflow for publishing the current
project stage. MiniMax remains deferred.

## Confirmed failures

The final verification exposed two independent problems:

1. `app/sites/douban_movie.py` has 66% statement coverage because the adapter's
   browser-facing success, blocked-page, and search-timeout branches are not
   exercised by unit tests.
2. The coverage threshold snippet in
   `docs/superpowers/tasks/core-12-final-verification.md` assumes JSON file keys
   use `/`. Coverage emits `\` keys on Windows, so the gate raises `KeyError`
   before evaluating the configured thresholds.

The existing parser and adapter behavior is not known to be incorrect. The repair
therefore must not modify production code merely to raise coverage.

## Repair design

### Adapter coverage

Extend `tests/test_douban_parser.py` with small in-memory fake page objects. Tests
will exercise observable adapter behavior without launching a browser or visiting
Douban:

- search returns parsed candidates after a result marker appears;
- search converts a missing result marker into `PageChangedError`;
- search stops on blocked HTML before submitting a query;
- detail fetch stops on blocked HTML;
- detail fetch parses a valid result using the page's canonical URL.

Mocks will be limited to the DrissionPage boundary. Production parsing and adapter
methods remain real. The focused coverage run must show
`app/sites/douban_movie.py` at or above 80% before the full suite is run.

### Portable coverage gate

Update only the embedded Python snippet in
`docs/superpowers/tasks/core-12-final-verification.md`. Normalize each coverage
JSON key with `name.replace('\\', '/')`, build a normalized lookup, and retain
the same three module names and 80% thresholds. This keeps the gate equivalent on
Windows and POSIX without changing coverage configuration or adding a helper
script.

### Final verification

Run the Core 12 gates from the absolute worktree path in their documented order:
pytest, coverage, threshold check, pip check, local `data:` browser smoke,
approved workbook contract, Git cleanliness and secret scan, and tracked runtime
artifact scan. No real Douban or MiniMax request is permitted. A missing approved
workbook or any other gate failure stops the release claim and is reported without
an improvised repair.

## Documentation deliverables after repair

Create a Core stabilization and release-readiness implementation plan under
`docs/superpowers/plans/`. The plan will use checkbox-sized TDD steps, exact file
boundaries, exact commands, expected outputs, stop conditions, and a complete
copyable operating prompt for each task. Planned work will cover portable local
verification, offline browser contracts, controlled workbook evidence, CI/release
gates, and handoff readiness. MiniMax will be listed as explicitly deferred and
will not be implemented by that plan.

Create a separate current-stage Git management prompt under
`docs/superpowers/prompts/`. It will guide a less capable model through branch and
remote checks, scoped staging, fresh verification, secret/runtime-artifact checks,
terse commits, pushing the current feature branch, and opening a draft PR to
`main`. It will prohibit direct pushes to `main`, destructive cleanup, unrelated
staging, force pushes, and automatic merging.

## Publication

After all deliverables pass fresh verification, inspect the complete diff, stage
only files created or modified for this scope, commit intentionally, push the
existing `feat/browser-bot-demo` branch to `JJ704sd/DataAnt`, and open a draft PR
against the repository's default branch. Authentication or remote mismatches stop
publication rather than triggering credential changes or alternate destinations.

## File boundaries

Expected tracked changes for the completed scope:

- Modify: `tests/test_douban_parser.py`
- Modify: `docs/superpowers/tasks/core-12-final-verification.md`
- Create: `docs/superpowers/specs/2026-07-15-core-final-verification-repair-design.md`
- Create: one Core stabilization plan in `docs/superpowers/plans/`
- Create: one current-stage Git prompt in `docs/superpowers/prompts/`

No production source, dependency, workbook, secret, browser profile, diagnostic
artifact, or MiniMax file is part of the tracked change set.

## Acceptance criteria

- Focused Douban adapter coverage is at least 80%.
- The documented coverage threshold snippet succeeds with Windows-style keys and
  remains valid for POSIX-style keys.
- Every Core 12 gate completes successfully using the approved local artifacts.
- The new plan contains executable prompts suitable for lower-capability models.
- The Git prompt matches the current branch-based draft-PR workflow.
- The final diff contains only the declared files and no secrets or runtime
  artifacts.
- Publication creates a pushed feature branch and draft PR; it does not merge.
