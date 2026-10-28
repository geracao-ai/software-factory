# Usage and cost

Every job keeps a running account of what it cost. The account starts when the
job is created and ends when it merges or goes to a human, and it adds up into
a project ledger, so you can see what each feature or bug fix cost and what the
project has cost so far.

```
job created ──► spec ──► build ──► READY ──► review rounds ──► approver ──► merged / needs-human
startedAt                          │                                 │              │
                                   ▼                                 ▼              ▼
                         checkpoint pr-opened              checkpoint reviewed  checkpoint closed
                         (what a PR would cost             (+ review rounds,    (endedAt, total;
                          by the time it opens)             fixes, approval)     ledger updated)
```

## What is recorded

Per agent run, per job, and for the whole project:

| Measure | Detail |
| ------- | ------ |
| Tokens  | `input`, `output`, `cache_read`, `cache_write_5m`, `cache_write_1h`, by model |
| Cost    | USD by model and in total, from `factory/pricing.json` |
| Model and effort | the model each request ran on and its effort level (`low` … `max`) |
| Context | the largest prompt one request sent (input + cache read + cache write) |
| Time    | `startedAt`, `endedAt`, wall time, and active time per agent |
| Work    | lines added and removed, files changed, commits, merged or not |
| Tools   | tool calls, tool errors, and edits (Edit, Write, NotebookEdit) accepted or rejected |
| Who     | by agent (`spec-writer`, `builder`, each reviewer, `approver`, `orchestrator`) and by phase |
| Ids     | the Claude Code session ids and agent ids, to join with OpenTelemetry data |

## How it is collected

Claude Code writes a transcript for every session, and one per subagent. Every
API request in it carries its `model`, `effort` and full `usage`: input, output,
cache read, and cache creation split by TTL. Summing those per request gives
the whole run, output tokens included, which the last response's usage alone
doesn't.

- **After every agent**: the `SubagentStop` hook in `.claude/settings.json` runs
  `factory/bin/usage.py hook`. It reads the agent's transcript, finds the job
  from the `Job folder:` line of its prompt, and appends one line to
  `factory/jobs/<job-id>/usage.jsonl` with that agent's usage. It also appends
  the orchestrator session's own usage since the previous agent. A resumed
  agent (the builder after a review round) only adds its new requests. The
  `bug-reporter`'s usage goes into the report folders it wrote and moves with
  them into the job.
- **At each checkpoint**: the orchestrator runs
  `factory/bin/usage.py checkpoint <job-id> pr-opened|reviewed|closed`. It adds
  up `usage.jsonl`, reads lines and commits from git, and writes `usage.json`
  (data) and `usage.md` (tables; the dashboard shows it in the job's drawer and
  the cost on its card).
- **On close**: `closed` replaces the job's line in `factory/ledger.jsonl` and
  rebuilds `factory/LEDGER.md`. When a job merges, the orchestrator also runs
  `usage.py ledger --readme`, which rewrites the block between
  `<!-- factory-ledger:start -->` and `<!-- factory-ledger:end -->` in
  `README.md`, and commits the three files.

The ledger files are committed; everything in `factory/jobs/` stays runtime
state. Run `python3 factory/bin/usage.py ledger --readme` at any time to
rebuild the tables.

## Accuracy

- **Cost is an estimate.** It is tokens × the prices in `factory/pricing.json`
  (Anthropic first-party API rates). Bedrock, Vertex, negotiated discounts and
  subscription plans differ: edit the file to match what you pay. A model that
  isn't in the file is counted in tokens and listed as unpriced.
- **A few internal requests are not in transcripts**: the auto-mode
  permission classifier, the summarizer behind WebFetch, and session titles.
  In the session that built this, they came to about 7% of the cost, mostly
  cheap cache reads. OpenTelemetry (below) counts them.
- **Approving from another session** (`/factory approve` in a session that
  spawned no agent for the job) doesn't add that session's few requests.

## OpenTelemetry, for exact and fleet-wide numbers

Claude Code exports its own metrics and events over OpenTelemetry. They count
every request, including the internal ones above, and use Claude Code's own
cost calculation. They need a backend (an OTLP collector, Prometheus, Datadog,
Honeycomb, Grafana…). Turn them on for everyone who runs the factory in
`.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
    "OTEL_RESOURCE_ATTRIBUTES": "factory.repo=my-app"
  }
}
```

| Metric | Attributes |
| ------ | ---------- |
| `claude_code.token.usage` | `type` (`input`, `output`, `cacheRead`, `cacheCreation`), `model`, `effort`, `query_source`, `agent.name` |
| `claude_code.cost.usage` | `model`, `effort`, `query_source`, `agent.name` |
| `claude_code.lines_of_code.count` | `type` (`added`, `removed`), `model` |
| `claude_code.commit.count`, `claude_code.pull_request.count` | |
| `claude_code.active_time.total` | `type` (`user`, `cli`) |
| `claude_code.code_edit_tool.decision` | `tool_name`, `decision` (`accept`, `reject`), `language` |

With `OTEL_LOGS_EXPORTER` set, events arrive one by one:
`claude_code.api_request` (model, cost, duration, every token type),
`claude_code.api_error`, `claude_code.tool_result`, `claude_code.tool_decision`,
`claude_code.user_prompt` (text redacted unless `OTEL_LOG_USER_PROMPTS=1`) and
`claude_code.subagent_completed`. Events carry `agent_id` and
`parent_agent_id`; metrics carry only `agent.name`, and name custom agents
`custom` unless `OTEL_LOG_TOOL_DETAILS=1`.

To join OpenTelemetry data to a job, filter by the `sessions` (`session.id`)
and `agent_ids` (`agent_id` on events) in the job's `usage.json`, between its
`startedAt` and `endedAt`. Every attribute is listed in Claude Code's
[monitoring reference](https://code.claude.com/docs/en/monitoring-usage).
