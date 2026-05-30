# Handoff — Apple Reminders sync (2026-05-30, evening pause)

**For the next Claude (any model — Sonnet recommended for cost):** finish Tasks 14–22 of the Apple Reminders implementation plan. Tasks 1–13 are done and committed. The remaining work is mostly verbatim transcription from the plan + a single design-heavy task (Task 14, the sync service).

## Worktree

- Path: `/Users/amit/Documents/Code/Irma/.claude/worktrees/feat+reminders-sync`
- Branch: `worktree-feat+reminders-sync`
- Tip: `a0fedfc` (`feat(reminders): inbox-project bootstrapper`)
- Plan: `docs/superpowers/plans/2026-05-30-apple-reminders-sync.md` (read-only — already amended)
- Spec: `docs/superpowers/specs/2026-05-30-apple-reminders-sync-design.md` (read-only — already amended)

**Hard rule:** stay inside this worktree. Never `cd` to `/Users/amit/Documents/Code/Irma`, never `git checkout` to another branch. A separate Claude session has uncommitted work on `feat/chat-tools-parity` at the main checkout — touching it breaks them. Verify `git branch --show-current` returns `worktree-feat+reminders-sync` before any commit.

## What's done

12 implementation commits on top of the spec/plan + 2 amendments. Swift helper builds clean and runs; Python integrations package has DTOs, async bridge, schema migration, repos extended with linkage columns, planner (pure function, 14 passing tests), and inbox bootstrapper. 164-baseline plus all new tests pass (~57 tests total in `tests/integrations/`).

Most recent commits (newest first):

```
a0fedfc feat(reminders): inbox-project bootstrapper
482d109 feat(reminders): pure-function per-calendar reconciliation planner
4a2defe feat(reminders): persist reminder linkage on Task and Project rows
324764f feat(reminders): async ReminderBridge + python fake helper
32eea0a feat(reminders): pydantic DTOs for helper JSON surface
b2db62d feat(reminders): wire CLI and ship native-arch binary artifact
f9c66fb docs(plans): complete one-list-per-project amendment (Tasks 12-22)
7502463 docs(handoff): apple reminders sync — mid-afternoon pause
df06234 docs(plans): partial amendment for one-list-per-project (Tasks 8-11)
d9e74ad feat(reminders): refit helper for one-list-per-project architecture
7ad1abd docs(specs): amend — one Reminders list per Project
... (older Swift Tasks 1–5)
```

## What's left (in order)

| Task | Effort | Notes |
|---|---|---|
| **14** ReminderSyncService | **HEAVY** — ~200 LOC + 5 integration tests | The only design-heavy task remaining. Plan spells out a 4-phase apply algorithm in prose; you write the Python. Uses the fake helper for tests, just like the bridge tests. |
| 15 Settings | trivial | Add 4 fields to `irma_api/config.py::Settings` and a small test. Plan has verbatim code. |
| 16 IntegrationsStatus extension | trivial | Add 3 fields to the existing `IntegrationsStatus` model in `routers/integrations.py`. Plan has verbatim code. |
| 17 `/integrations/reminders` router | small | New router with `POST /link`, `DELETE /link`, `POST /sync`. Plan has verbatim code. |
| 18 Lifespan wiring | small | Edit `app.py` to construct `ReminderBridge` + a factory for `ReminderSyncService` if the helper binary exists. Plan has verbatim code. |
| 19 Scheduler tick | small | Modify `runtime/scheduler.py` to accept an optional second periodic job for reminders sync. Plan has verbatim code. |
| 20 Post-write sync triggers | small | Add `_trigger_reminder_sync` helper in `routers/integrations.py` and call it from project/task writes. Plan has verbatim code. |
| 21 Opt-in E2E test | small | Single pytest file marked `skipif(not os.environ.get("IRMA_REMINDERS_E2E"))`. Plan has verbatim code. |
| 22 README | trivial | Append a section to `services/api/README.md`. Plan has verbatim text. |

After Task 22 the branch is feature-complete. Task 31 (full-branch code review) was deferred — the per-task tests + spot-checks are the safety net; you can skip it. Task 32 is "invoke `superpowers:finishing-a-development-branch`" which is the wrap-up workflow.

## How to execute (token-conservation mode)

The original plan was per-task subagent dispatch with two-stage review. We switched mid-session to **in-controller direct implementation** because the dispatch overhead was burning tokens for verbatim transcription tasks. Keep doing that:

1. Read the next task's section from the plan.
2. `Write`/`Edit` the files exactly as the plan specifies.
3. Run `cd services/api && uv run pytest <new test file>` (or `swift build` for Swift work).
4. If green, `git add <specific files>` and commit with the message the plan specifies.
5. Move to the next task.

**No subagent dispatches**, except optionally for Task 14 (the sync service) if you feel it'd help — the plan provides the algorithm prose + dataclass interface + 5 test scenarios but not the implementation. You can do it in-controller if you trust your reading of the algorithm.

## Environment caveats (don't relearn these)

- **Xcode Command Line Tools only** — no full Xcode. Consequences:
  - `swift test` (XCTest) doesn't work. Verification gate for Swift is `swift build` (the plan was already amended for this).
  - `swift build -c release --arch arm64 --arch x86_64` doesn't work either (`xcbuild` missing). The current `build.sh` builds native-arch only — you don't need to touch it.
- **Top-level `await` in main.swift** — Swift 5.7+. The original plan used `DispatchSemaphore` to wait for an async Task; that deadlocked on EventKit calls. The committed main.swift uses top-level await instead. Already shipped — you don't need to touch it.
- **Pydantic v2 + JSON dates** — when serializing pydantic models containing `date` objects to JSON, use `model_dump(mode="json", ...)`, not plain `model_dump`. The bridge already does this; if you write similar serialization in Task 14, follow the same pattern.

## Open issue, not yours to fix

A subagent earlier today accidentally committed `9553173` (an old-architecture `EventKitRemindersClient.swift`) onto `feat/chat-tools-parity` (the user's other branch, not this worktree). Don't try to revert it — the user will handle it manually when they coordinate with the other Claude session. The correct version of that file lives here at commit `d9e74ad`.

## Quick sanity check before starting

```bash
cd /Users/amit/Documents/Code/Irma/.claude/worktrees/feat+reminders-sync
git branch --show-current     # → worktree-feat+reminders-sync
git rev-parse HEAD            # → a0fedfc...
git status                    # → clean
cd services/api
uv run pytest -q              # → all passing (no failures)
```

If any of those don't match, stop and report back to the user before changing anything.

## After Task 22

Final state should be: 9 new feature commits on top of `a0fedfc`, all tests green, the helper binary still in `tools/reminders-helper/bin/`. At that point the branch is ready for the user to merge or open a PR. They'll do the merge/PR themselves; you don't need to push or trigger anything.
