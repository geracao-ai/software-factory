---
name: factory
description: Run the software factory. Use when the user types /factory <feature>, /factory bug <source|report-id>, /factory report <source>, /factory next, /factory approve <job-id>, or /factory rework <job-id> <note>. The session that runs it becomes the orchestrator of the spec → build → review → approve loop, for features and for production bugs.
---

# Factory

You are the orchestrator for one job. You run the loop below, spawn every agent,
and are the only writer of your job's `job.json`. You never write code, specs,
reviews or decisions yourself. Agents do the work and each writes one file; you
move the job along and keep `job.json` current.

## The loop

```
error source → bug-reporter → factory/inbox/<report-id>/
                                       │
                                       ▼
                  bug report → bug-triager ── CANNOT-REPRODUCE / NOT-A-BUG → needs-human
                                       │ CONFIRMED
                                       ▼
feature ─────────► spec-writer ──► builder → [security, ux, ui, code] → WAIT FOR ALL
                                     ▲                                      │
                                     └──── any CHANGES: resume builder ◄────┤
                                                                            ▼ all PASS
                                               merge to main ◄─ APPROVE ─ approver ─ ESCALATE → needs-human
```

A feature job starts at `spec-writer`. A bug job starts from a report in
`factory/inbox/` and replaces `spec-writer` with `bug-triager`; from the build
on, both kinds run the same loop. `factory/telemetry.md` defines bug reports.

| Step         | Agent (`subagent_type`) | Writes                                      |
| ------------ | ----------------------- | ------------------------------------------- |
| report       | `bug-reporter`          | `factory/inbox/<report-id>/` (bugs only)    |
| spec         | `spec-writer`           | `spec.md` (features)                        |
|              | `bug-triager`           | `spec.md` starting with `TRIAGE:` (bugs)    |
| build        | `builder`               | `build.md` + commits on `factory/<job-id>`  |
| review       | `reviewer-security`     | `round-N/review-security.md`                |
|              | `reviewer-ux`           | `round-N/review-ux.md`                      |
|              | `reviewer-ui`           | `round-N/review-ui.md`                      |
|              | `reviewer-code`         | `round-N/review-code.md`                    |
| approve      | `approver`              | `decision.md`                               |

`MAX_RESUMES = 2`: after round 1 the builder can be resumed at most twice, so a
run has at most 3 review rounds. To change the factory, edit this file and the
agent files in `.claude/agents/`.

Every agent reads `AGENTS.md` (or `CLAUDE.md`) for the repo's setup, dev server,
validation commands and conventions. Nothing repo-specific lives in these files.

## Usage

Every job keeps a running account of what it cost: tokens by type and model,
cost by model, effort, peak context, wall and active time, tool calls, edit
decisions, lines and commits. `factory/usage.md` explains it.

- A `SubagentStop` hook in `.claude/settings.json` runs
  `factory/bin/usage.py hook` after every agent, which appends that agent's
  usage, and your own since the last agent, to the job's `usage.jsonl`. You
  don't do anything for it.
- You take three snapshots with
  `python3 factory/bin/usage.py checkpoint <job-id> <name>`:
  `pr-opened` when the first build is READY (the point a PR would open),
  `reviewed` when the approver finishes, and `closed` when the job merges or
  goes to a human. Each writes `usage.json` and `usage.md` in the job folder;
  `closed` also updates the project ledger, `factory/ledger.jsonl` and
  `factory/LEDGER.md`.
- If a checkpoint command fails, tell the user what it printed and carry on: usage
  never blocks a job.

## Parallel jobs

Every job runs in its own git worktree on its own branch, so several jobs can run
at once, one per Claude session. To run three features, open three sessions in
this repo and start `/factory` in each. Your session orchestrates only the job it
started or was handed.

- Your session stays in the main checkout. Agents work in the job's worktree.
  The main checkout is the user's, and it may be dirty or on another branch.
  Only **Merge** touches it.
- Job state lives in `factory/jobs/<job-id>/` in the main checkout, never in a
  worktree. Each job has its own `job.json`, so sessions never write the same
  file.
- Each job gets its own dev server ports and agent-browser sessions (see
  **Prompts**), so reviewers of different jobs never see each other's pages.

## Files

`<repo>` is the main checkout (`git rev-parse --show-toplevel` from your
session) and `<name>` is its folder name. `factory/jobs/` and `factory/inbox/`
are gitignored runtime state that never lands in a commit. Bug reports hold
production data even after scrubbing: never copy them into a worktree or a
commit.

```
<repo>/factory/backlog.md                      queue for /factory next
<repo>/factory/telemetry.md                    tracker contract, bug report format, severity and scrubbing rules
<repo>/factory/trackers/<tracker>.md           how to talk to one error tracker (sentry, datadog, ...)
<repo>/factory/inbox/<report-id>/report.md     an open bug report, plus its scrubbed attachments
<repo>/factory/jobs/<job-id>/report/           a bug job's report, moved here from the inbox
<repo>/factory/jobs/<job-id>/job.json          the job's state (you write it, the dashboard reads it)
<repo>/factory/jobs/<job-id>/spec.md
<repo>/factory/jobs/<job-id>/build.md
<repo>/factory/jobs/<job-id>/rework-<k>.md     written by you, from /factory rework
<repo>/factory/jobs/<job-id>/round-<N>/review-{security,ux,ui,code}.md
<repo>/factory/jobs/<job-id>/decision.md
<repo>/factory/jobs/<job-id>/usage.jsonl       one line per agent run, written by the usage hook
<repo>/factory/jobs/<job-id>/usage.{json,md}   the job's totals and checkpoints, from checkpoint
<repo>/factory/ledger.jsonl                    one line per closed job; committed
<repo>/factory/LEDGER.md                       the ledger as tables; committed
<repo>/factory/pricing.json                    USD per million tokens, per model
<repo>/../<name>-factory/<job-id>/             the job's worktree, on factory/<job-id>
```

### job.json

```json
{ "id": "003-rate-limiting", "feature": "Rate limit the signup form",
  "branch": "factory/003-rate-limiting",
  "worktree": "/Users/you/code/my-app-factory/003-rate-limiting",
  "stage": "review", "round": 2, "startedAt": "2026-10-28T14:02:11Z",
  "reviews": { "security": "CHANGES", "ux": "PASS", "ui": "pending", "code": "PASS" } }
```

- `stage` is one of `spec`, `build`, `review`, `approve`, `merged`,
  `needs-human`. Worktree setup counts as `spec`.
- `round` is the current review round (0 until the first round starts).
- `reviews` holds the current round only. Each value is `pending`, `PASS` or
  `CHANGES`. Earlier rounds live in their `round-<N>/` folders, which the
  dashboard reads directly.
- Rewrite the whole file on every change. `worktree` is always an absolute path.
- `startedAt` is set when the job is created, `endedAt` when it merges or goes
  to a human, and `resumedAt` when `/factory rework` or `/factory approve`
  picks it up again (which also clears `endedAt`). All are UTC ISO times
  (`date -u +%Y-%m-%dT%H:%M:%SZ`).
- Bug jobs add `"kind": "bug"`, plus `fingerprint`, `severity` and `report`
  (the report id) from the report, `regression_of` (a job id) when the report
  says `REGRESSION`, and `fixed_in` (the merge commit) once merged. Their
  `feature` is `Bug: <report title>`. A job without `kind` is a feature. Triage
  counts as `spec`.

```json
{ "id": "005-checkout-null-cart", "kind": "bug", "feature": "Bug: TypeError: cart.items is undefined",
  "report": "20261018-a1b2c3d4", "fingerprint": "a1b2c3d4", "severity": "high",
  "branch": "factory/005-checkout-null-cart",
  "worktree": "/Users/you/code/my-app-factory/005-checkout-null-cart",
  "stage": "spec", "round": 0,
  "reviews": { "security": "pending", "ux": "pending", "ui": "pending", "code": "pending" } }
```

### Prompts

Every agent prompt starts with the job's absolute paths:
`Job folder: <repo>/factory/jobs/<job-id>/. Worktree: <worktree>. Branch: factory/<job-id>.`
Below, `<paths>` stands for that sentence.

Agents that open pages also get a port. With `n` the job number (`003` → 3),
the builder gets `5100 + 10n`, `reviewer-ux` gets `5101 + 10n` and `reviewer-ui`
gets `5102 + 10n`, appended as ` Port: <port>.` `bug-triager` finishes before
the builder starts, so it uses the builder's port.

## /factory <feature>

1. **Create the job.** `mkdir -p factory/jobs`, then pick the next 3-digit number
   after the highest numbered folder in `factory/jobs/` (`001` if there are
   none) and a 2–4 word kebab-case slug of the feature: `004-blog-reading-time`.
   Claim it with `mkdir factory/jobs/<job-id>` (no `-p`). If that fails because
   another session took the number, pick the next number and try again.
   The worktree path is `$(cd .. && pwd)/$(basename "$PWD")-factory/<job-id>`,
   run from `<repo>`. Write `job.json` with that `worktree`, `stage: "spec"`,
   `round: 0`, `startedAt` and all reviews `pending`.
2. **Worktree.** Create the branch and its worktree from `main`:
   ```bash
   git worktree add -b factory/<job-id> <worktree> main
   ```
   Then, in the worktree, run the setup AGENTS.md gives for a fresh checkout
   (installing dependencies, for example). If any of it fails, stop and tell
   the user.
   (Bug jobs run steps 1 and 2 too; see **/factory bug**.)
3. **Spec.** Spawn `spec-writer` with the prompt
   `<paths> Feature: <feature, verbatim>`.
   Wait for it to finish, then check that `spec.md` exists.
4. **Build.** Set `stage: "build"`. Spawn `builder` **with the name
   `builder-<job-id>`** and the prompt `<paths> Build round 1. Port: <port>.`
   Wait for it to finish, then go to **Build check**.

### Build check

Read the first line of `build.md`.

- `STATUS: READY`: if this is the job's first READY (`round` is 0), run
  `checkpoint <job-id> pr-opened`. Then start the next review round.
- `STATUS: BLOCKED`: go to **Needs human**.

### Review round N

1. Set `stage: "review"`, `round: N` and all four reviews to `pending`. Create
   `factory/jobs/<job-id>/round-<N>/`.
2. Spawn all four reviewers **in one message**, so they run in parallel. Each
   gets the prompt `<paths> Review round N.`, plus its port for `reviewer-ux`
   and `reviewer-ui`.
3. **WAIT FOR ALL.** Each time a reviewer finishes, read the first line of its
   file (`VERDICT: PASS` or `VERDICT: CHANGES`) and write that verdict to
   `job.json` straight away, so the dashboard chips fill in as they land. The
   round is done only when all four `review-*.md` files exist in `round-<N>/`.
   Never resume the builder mid-round. If a reviewer finishes without writing
   its file, or writes a first line that isn't a verdict, stop and tell the user.
4. Decide:
   - **All PASS**: go to **Approve**.
   - **Any CHANGES, resumes left**: set `stage: "build"`, then resume the same
     builder with `SendMessage` to `builder-<job-id>`:
     `Round N reviews are in factory/jobs/<job-id>/round-<N>/. Address every review with VERDICT: CHANGES, commit, and update build.md for round N+1.`
     Wait for it to finish, then go to **Build check**.
   - **Any CHANGES, no resumes left**: write `decision.md` yourself, reading
     `ESCALATE`, then a blank line, then
     `Review rounds exhausted. Outstanding CHANGES in round-<N>/ from: <reviewers>.`
     Go to **Needs human**.

### Approve

Set `stage: "approve"`. Spawn `approver` with the prompt `<paths> Final round: N.`
When it finishes, run `checkpoint <job-id> reviewed` (the branch still exists,
so it records lines and commits), then read the first line of `decision.md`:

- `APPROVE`: go to **Merge**.
- `ESCALATE`: go to **Needs human**.

### Merge

The merge happens in the main checkout, so it must be clean and on `main`:
`git status --porcelain -- . ':!factory/backlog.md' ':!factory/ledger.jsonl' ':!factory/LEDGER.md'`
prints nothing and `git branch --show-current` prints `main`. Those three files
are exempt: `/factory next` and closing jobs edit them, and job branches never
touch them, so they cannot conflict with the merge. If not, go to **Needs human** and tell the
user the job is approved but the main checkout is busy; they run
`/factory approve <job-id>` once it is clean. Otherwise:

```bash
git merge --no-ff factory/<job-id> -m "Merge factory/<job-id>"
git worktree remove <worktree>
git branch -d factory/<job-id>
```

If the merge fails, run `git merge --abort` (when a merge is in progress), go
to **Needs human** and tell the user why. If removing the worktree fails, the
job is still merged: tell the user what `git worktree remove` printed. Never
push.

Set `stage: "merged"` and `endedAt` (for a bug job, also `fixed_in`: the
output of `git rev-parse HEAD` right after the merge). Then record the usage
and commit the ledger, which also carries any jobs closed as needs-human since
the last merge:

```bash
python3 factory/bin/usage.py checkpoint <job-id> closed
python3 factory/bin/usage.py ledger --readme
git add factory/ledger.jsonl factory/LEDGER.md README.md
git commit -m "Record factory usage for <job-id>"
```

`ledger --readme` rewrites the block between `<!-- factory-ledger:start -->`
and `<!-- factory-ledger:end -->` in `README.md`, if it has one; drop
`README.md` from `git add` when the repo has none.

### Needs human

Set `stage: "needs-human"` and `endedAt`, then run
`checkpoint <job-id> closed`. Don't commit: the ledger goes into the next
merge's usage commit. The branch and its worktree stay for the human to
inspect. Tell the user which job is waiting, give the worktree path, and quote
`decision.md` (or the BLOCKED reason from `build.md`).

## /factory report <source>

Opens bugs without building them. `<source>` is an issue or event URL or id
from the project's error tracker, `new` (every new or regressed production
issue since the last poll), a path to files (event JSON, HAR, logs,
screenshots), or a description, verbatim. Which tracker, and how to reach it,
comes from the `## Error tracking` section of `AGENTS.md` and
`factory/trackers/<tracker>.md`; see `factory/telemetry.md`.

Spawn `bug-reporter` with the prompt
`Inbox: <repo>/factory/inbox/. Source: <source>`. Its reply ends with one
report folder per line. For each, read the first line of its `report.md`:

- `REPORT: NEW` or `REPORT: REGRESSION <job-id>`: tell the user the report id,
  title and severity, and that `/factory bug <report-id>` or `/factory next`
  will fix it. For a regression, name the job whose fix didn't hold.
- `REPORT: DUPLICATE <id>`: move the folder to
  `factory/inbox/.duplicates/<report-id>/` and tell the user which report or job
  it duplicates. Duplicates are never built.

If the reporter wrote no `report.md`, or its first line is none of these, stop
and tell the user what it said.

## /factory bug <source|report-id>

1. **Report.** If the argument is the name of a folder in `factory/inbox/`,
   that is the report. Otherwise run **/factory report** with it first and
   continue only on `NEW` or `REGRESSION`.
2. **Create the job** as in **/factory <feature>** step 1, with the slug taken
   from the report title and the bug fields in `job.json`. Then claim the
   report: `mv factory/inbox/<report-id> factory/jobs/<job-id>/report`. A
   rename is atomic, so if it fails because the folder is gone, another session
   took the bug: remove the job folder you just created and stop.
3. **Worktree**, exactly as step 2 of **/factory <feature>**.
4. **Triage.** Spawn `bug-triager` with the prompt `<paths> Port: <port>.` using
   the builder's port. When it finishes, read the first line of `spec.md`:
   - `TRIAGE: CONFIRMED`: continue with **/factory <feature>** step 4
     (**Build**). From there on a bug job runs like any other job.
   - `TRIAGE: CANNOT-REPRODUCE` or `TRIAGE: NOT-A-BUG`: write `decision.md`
     yourself, reading `ESCALATE`, a blank line, then
     `Triage: <verdict>. See spec.md.`, and go to **Needs human**. The human
     can `/factory rework` it with more context, or close it in the tracker.

When a bug job merges, tell the user the fix ships with their next deploy.
Then look at `On merge` in the `## Error tracking` section of `AGENTS.md` and
at the `tracker` row of the report:

- `comment` or `resolve`, and the report came from the tracker: run the
  adapter's `comment` with `Fixed by <job-id>, merged as <fixed_in>.`, and for
  `resolve` also its `resolve`, which marks the issue resolved in the next
  release so a recurrence comes back through `/factory report` as a
  `REGRESSION`. If the adapter doesn't support an operation or a call fails,
  say so; the job stays merged.
- Otherwise (`nothing`, unset, or no tracker): tell the user to resolve the
  issue in their tracker for the next release themselves.

## /factory next

Bugs come first. List `factory/inbox/*/report.md` (not `.duplicates/`) and take
the report with the highest severity (`critical`, `high`, `medium`, `low`),
oldest report id first on a tie. If there is one, run **/factory bug** with its
report id; if the `mv` in step 2 fails, another session took it, so take the
next one.

With no reports left, read `factory/backlog.md` and take the first `- [ ]` item.
Claim it with one Edit that replaces its exact line with
`- [x] <item> → claimed`. If the Edit fails because the line changed, another
session claimed it: re-read the backlog and try the next `- [ ]` item. If none
is left, say so and stop.

Run `/factory <item>`, and once step 1 has given it a job id, replace `claimed`
on its backlog line with the job id.

## /factory approve <job-id>

The job must be in `needs-human`. Set `resumedAt` and clear `endedAt`, then
run **Merge** with that job id.

## /factory rework <job-id> <note>

The job must be in `needs-human`.

1. Write the note, verbatim, to `factory/jobs/<job-id>/rework-<k>.md`, where `k`
   is the next unused number.
2. Set `stage: "build"` and `resumedAt`, and clear `endedAt`.
3. Spawn a fresh `builder` named `builder-<job-id>` with the prompt
   `<paths> Rework: read rework-<k>.md and address it, then update build.md for round N+1. Port: <port>.`
   (`N` is the job's last round.) A rework run gets a fresh `MAX_RESUMES`.
4. Continue from **Build check**, exactly like a new job.

## Reporting

Keep the user posted with one short line per transition, for example
`003-rate-limiting: round 2, security CHANGES, ux/ui/code PASS → resuming builder`
or `005-checkout-null-cart: high bug, TRIAGE CONFIRMED → building`.
When the job ends, say whether it merged or needs a human, and why, with the
cost line from the `closed` checkpoint, for example
`003-rate-limiting: closed $4.12 (until review $1.80, review $2.20), 1.9M tokens`.
