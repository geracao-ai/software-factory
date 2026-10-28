# Software Factory for Claude Code

A small, visual software factory built from one Claude Code skill, nine
subagents and plain markdown files. You type `/factory <feature>` and agents
write a spec, build it on its own branch, review it from four angles, and either
merge it to `main` or hand it to you. Production errors take the same path:
`/factory report <source>` turns an error, a HAR or a tracker issue into a bug
report, and `/factory bug` reproduces it, fixes it with a regression test, and
runs it through the same loop.

```
error source → bug-reporter → factory/inbox/ → bug-triager ─┐ CONFIRMED
                                                            ▼
feature ─────────────────────────────────────► spec-writer → builder → [security, ux, ui, code] → WAIT FOR ALL
                                                               ▲                                      │
                                                               └──── any CHANGES: resume builder ◄────┤
                                                                                                      ▼ all PASS
                                                         merge to main ◄─ APPROVE ─ approver ─ ESCALATE → needs-human
```

This folder is laid out like a repo root, so you can copy it straight into
yours.

```
.claude/
  settings.json                  the SubagentStop hook that records each agent's usage
  skills/factory/SKILL.md        the orchestrator: runs the loop, writes job.json
  agents/                        one file per agent in the loop
    bug-reporter.md              sonnet  scrubs and groups an error into factory/inbox/<report-id>/
    bug-triager.md               opus    reproduces a bug, writes spec.md with a TRIAGE verdict
    spec-writer.md               opus    writes spec.md
    builder.md                   opus    commits on factory/<job-id>, writes build.md
    reviewer-security.md         opus    writes round-N/review-security.md
    reviewer-ux.md               sonnet  writes round-N/review-ux.md
    reviewer-ui.md               sonnet  writes round-N/review-ui.md
    reviewer-code.md             sonnet  writes round-N/review-code.md
    approver.md                  opus    writes decision.md
factory/
  backlog.md                     queue for /factory next
  telemetry.md                   tracker contract, what the app should capture, bug report format
  trackers/                      one adapter per error tracker: sentry, datadog, bugsnag, rollbar, custom
  inbox/                         open bug reports, one folder each (runtime state)
  usage.md                       how cost and usage are recorded, and OpenTelemetry
  pricing.json                   USD per million tokens, per model
  bin/usage.py                   the usage collector (hook, checkpoints, ledger)
  ledger.jsonl, LEDGER.md        one line per closed job, and the same as tables (committed)
  dashboard.html                 the visual board
  jobs/                          one folder per job (two examples included)
BUILD_PROMPT.md                  the prompt that built the original factory
```

## How it works

- The Claude Code session that runs `/factory` becomes the orchestrator. It
  spawns every agent and is the only writer of the job's `job.json`.
- Agents get their context from files, not the conversation, and each writes
  only its own file. Every review starts with `VERDICT: PASS` or
  `VERDICT: CHANGES`; `decision.md` starts with `APPROVE` or `ESCALATE`.
- The four reviewers run in parallel. A round is done only when all four files
  exist. If any says CHANGES, the same builder is resumed (at most twice).
- Each job gets its own git worktree next to your repo
  (`../<repo>-factory/<job-id>/`) on a `factory/<job-id>` branch. Open several
  Claude sessions and run `/factory` in each to build features in parallel.

## Commands

```
/factory <feature>               run a new job through the loop
/factory report <source>         open bug reports from a tracker issue, `new` (poll), files (event, HAR, logs) or a description
/factory bug <source|report-id>  reproduce and fix a bug through the loop
/factory next                    fix the most severe open bug, or else run the first unchecked backlog item
/factory approve <job-id>        merge a needs-human job into main
/factory rework <job-id> <note>  send a needs-human job back to the builder with feedback
```

## Production bugs

`factory/telemetry.md` is the contract between your app and the factory: what
the factory needs from an error tracker, what the app should capture when it
fails (release SHA, symbolicated stack, breadcrumbs, trace id, grouping, PII
scrubbing at the source), the report format, severity levels and HAR scrubbing
rules.

The factory isn't tied to one vendor. Each project names its tracker in an
`## Error tracking` section of `AGENTS.md`, and `factory/trackers/<name>.md`
says how to reach it. Adapters ship for `sentry` (and GlitchTip), `datadog`,
`bugsnag`, `rollbar` and `custom` (your own endpoint or log store); add a file
for any other. Without a tracker, `/factory report` still takes HARs, event
files and descriptions.

```markdown
## Error tracking
- Tracker: sentry
- Base URL: https://sentry.io
- Project: acme/web-app
- Auth: $SENTRY_AUTH_TOKEN
- Production environment: production
- Release: git SHA
- On merge: resolve        # nothing (default) | comment | resolve
```

- **`bug-reporter`** reads the source as untrusted data, scrubs tokens, cookies
  and PII, fingerprints the error, and writes `factory/inbox/<report-id>/`. A
  report that matches an open job is a `DUPLICATE`; one that matches a merged
  job is a `REGRESSION`.
- **`bug-triager`** reproduces the bug in the job's worktree (a throwaway test,
  the dev server, or the traced code path), finds the root cause and writes
  `spec.md`. Its first acceptance criterion is always a regression test that
  fails on `main` and passes on the branch. If it can't reproduce the bug, the
  job goes to a human with the extra telemetry that would help next time.
- From there the builder writes the failing test first, fixes the cause in a
  separate commit, and the reviewers and approver check the red → green
  evidence.

Wire your tracker's *new issue* and *regression* alerts to a session that runs
`/factory report <issue-url>`, or schedule `/factory report new` to poll, and
run `/factory next` to work through the inbox.

## Usage and cost

Every job keeps a running account of what it cost, from the moment it is
created until it merges or goes to a human: tokens by type (input, output,
cache read, cache write) and model, cost by model, effort, peak context, wall
and active time, lines and commits, tool calls, and edits accepted or rejected.
Each agent run is one line, so you see what the builder cost compared with the
reviewers.

A `SubagentStop` hook records every agent from Claude Code's transcripts, with
no setup. The orchestrator takes three snapshots: **pr-opened** (first build
ready), **reviewed** (after the approver) and **closed** (merged or handed to
you). Closed jobs add up in `factory/ledger.jsonl` and `factory/LEDGER.md`,
and in the block below, which every merge updates. Costs are estimates from
`factory/pricing.json`; for exact, fleet-wide numbers, turn on Claude Code's
OpenTelemetry export. `factory/usage.md` explains both.

<!-- factory-ledger:start -->
No jobs closed yet.
<!-- factory-ledger:end -->

## Use it in your repo

1. Copy `.claude/` and `factory/` into your repo root.
2. Delete the example jobs in `factory/jobs/`, the checked items in
   `factory/backlog.md`, and `factory/ledger.jsonl` and `factory/LEDGER.md` if
   they have entries. To get the totals in your README, add the two
   `factory-ledger` comment lines above to it. Check `factory/pricing.json`
   against what you pay.
3. Add `/factory/jobs/` and `/factory/inbox/` to your `.gitignore`. Job
   folders and bug reports are runtime state, and reports hold production data.
4. Make sure your `AGENTS.md` (or `CLAUDE.md`) says how to set up a fresh
   checkout, start the dev server on a given port, and run your tests, build
   and lint, plus an `## Error tracking` section if you want production bugs. The agents carry nothing repo-specific; they read all of it from
   there.
5. Install the [`agent-browser`](https://github.com/vercel-labs/agent-browser)
   CLI if your project has pages to look at. The builder and the UX and UI
   reviewers use it to check the running app.
6. Commit everything on `main`, then run `/factory <feature>`.

The review checklists are deliberately general. Ask Claude to tailor them to
your stack: your framework, your security hot spots, and what the approver
should always escalate.

## Dashboard

```bash
cd factory && python3 -m http.server
```

Open <http://localhost:8000/dashboard.html>. Jobs move across the stages as
cards, review chips fill in as verdicts land, each card shows its cost so far,
and jobs that need you stand out. Click a card to read its markdown files,
`usage.md` included. It polls every two seconds, so leave it
open while jobs run.

## The example jobs

Both came from running the factory on [zazencodes.com](https://zazencodes.com),
a Vue + Firebase site. Serve the dashboard from this folder to click through
them.

- **001-blog-reading-time** passed all four reviews in round 1, but the approver
  escalated it because it edited a prerender script, which counts as a deploy
  change. A human read `decision.md` and ran `/factory approve`.
- **002-not-found-page** passed review and the approver merged it to `main` on
  its own.

## BUILD_PROMPT.md

The prompt used to build the original factory, kept verbatim for reference.
If you are copying this folder as a template, ignore it.

The factory has grown since then: it now runs each job in its own git worktree
and gives every job its own `job.json`, instead of the single `board.json` the
prompt describes, so several jobs can run at once.
