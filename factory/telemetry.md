# Telemetry and bug reports

How production errors become factory jobs. The app sends errors to an error
tracker, the `bug-reporter` agent turns an error into a **bug report** in
`factory/inbox/`, and the factory runs it through the same build → review →
approve loop as a feature.

```
production error ─► error tracker (any: see "Trackers" below)
                       │ alert / webhook / scheduled poll / a human with a HAR
                       ▼
               /factory report <source>     bug-reporter reads, scrubs, groups
                       ▼
               factory/inbox/<report-id>/   one folder per distinct bug
                       ▼
               /factory bug <report-id>     (or /factory next)
                       ▼
               bug-triager → builder → [security, ux, ui, code] → approver → main
```

The factory never depends on one vendor. This file defines what it needs from
a tracker; `factory/trackers/<name>.md` says how one vendor provides it; and
each project picks its tracker in `AGENTS.md`.

## 1. Choosing a tracker

The project declares its tracker in `AGENTS.md` (or `CLAUDE.md`) under an
`## Error tracking` heading:

```markdown
## Error tracking
- Tracker: sentry                     # a file name in factory/trackers/, without .md
- Base URL: https://sentry.io         # for self-hosted or regional instances
- Project: acme/web-app               # whatever the adapter says identifies it
- Auth: $SENTRY_AUTH_TOKEN            # env var names only, never the values
- Production environment: production
- Release: git SHA                    # what the app sends as its release
- On merge: nothing                   # nothing | comment | resolve
```

- **Tracker** names an adapter in `factory/trackers/`. To support a new
  service, copy the closest adapter and edit it.
- **Auth** lists environment variable names. Secrets never go in a file.
- **On merge** says what the factory may write back to the tracker when a bug
  job merges: `nothing` (the default), `comment` (link the job on the issue),
  or `resolve` (also mark it resolved in the next release). Writing to the
  tracker is the only outward action the factory takes, so it is off unless the
  project turns it on.

With no `## Error tracking` section, the factory still works: `/factory report`
accepts files (event JSON, HAR, logs, screenshots) and plain descriptions, and
says that no tracker is configured.

## 2. The tracker contract

Every adapter in `factory/trackers/` describes how to do these operations, and
how to map what comes back onto the report format in section 5.

| Operation | Needed     | What it does                                                                 |
| --------- | ---------- | ---------------------------------------------------------------------------- |
| `fetch`   | required   | From an issue or event URL or id: the error, stack trace, breadcrumbs, request, release, environment, first/last seen, event and user counts, and the tracker's group id |
| `list`    | optional   | New or regressed unresolved issues in production since a given time, for scheduled polling |
| `comment` | optional   | Add a note to an issue (the job id and branch)                              |
| `resolve` | optional   | Mark an issue resolved in the next release, so a recurrence counts as a regression |

An adapter may use the vendor's HTTP API with `curl`, its CLI, or an MCP tool
the session has. It also says how to recognise the vendor's URLs, and which of
the optional operations it can't do.

## 3. What the app should capture

The factory can only fix what the report lets it reproduce. These practices
are common to Sentry, Datadog, Bugsnag, Rollbar and OpenTelemetry-based setups;
a small `/api/errors` endpoint of your own can follow them too. You can build
the instrumentation with the factory itself: `/factory Add error telemetry as
described in factory/telemetry.md`.

- **Every uncaught error.** Global handlers (`window.onerror`,
  `unhandledrejection`), the framework's error boundary or error handler, and
  server-side uncaught exceptions plus a request middleware that reports 5xx
  responses.
- **Release and environment on every event.** The release is the deployed git
  commit SHA, so the triager can check out exactly the code that failed. The
  environment keeps production apart from preview and local builds.
- **Readable stack traces.** Upload source maps (or debug symbols) to the
  tracker at deploy time; don't serve them publicly.
- **Breadcrumbs.** The trail before the error: route changes, clicks (by
  selector, never typed values), console errors, and fetch/XHR calls with method,
  URL, status and duration but no bodies. Keep the last 20–50.
- **A trace id.** Propagate a request or trace id (W3C `traceparent` /
  OpenTelemetry) from browser to backend and include it in error responses, so a
  frontend error links to the backend logs for the same request.
- **Grouping.** Every event belongs to a group, so a thousand occurrences are
  one bug. Default: error type + top in-app frame + message with ids and numbers
  stripped. Add custom grouping rules for families the default splits or merges
  wrongly.
- **Privacy at the source.** Send no PII by default. Scrub in the SDK's
  before-send and before-breadcrumb hooks. Identify users by an opaque id only.
  Session replay, if you use it, masks all text and inputs.
- **Noise control.** Sample high-volume events, rate-limit, and ignore known
  noise: browser extensions, bots, `ResizeObserver loop` warnings, aborted
  requests on navigation.
- **Alerts on three things.** A new issue, a regression (a resolved issue seen
  again), and a spike. These are what should trigger `/factory report`.

## 4. Feeding the inbox

Anything can open a bug, as long as it ends up as a `/factory report <source>`
run (or writes a report folder in the format below itself). `<source>` is any of:

- an issue or event URL or id from the project's tracker (the adapter's
  `fetch`);
- `new`: every new or regressed production issue since the last poll (the
  adapter's `list`);
- a path to a file or folder: an event JSON, a HAR, a log excerpt, screenshots;
- a plain-text description from a human.

Common setups:

- **Tracker alert → Claude session.** Point the tracker's alert webhook (new
  issue, regression) at a scheduled task or a session that runs
  `/factory report <issue-url>`.
- **Scheduled poll.** A scheduled session runs `/factory report new` every hour.
- **Human.** Export a HAR (Chrome: *Save all as HAR (sanitized)*), describe what
  you did, and run `/factory report ./path/to/folder`.

`factory/inbox/` is runtime state, like `factory/jobs/`: gitignore it. It holds
production data even after scrubbing. The last poll time lives in
`factory/inbox/.last-poll` (an ISO timestamp).

## 5. Report format

`factory/inbox/<report-id>/`, where `<report-id>` is `<YYYYMMDD>-<fingerprint>`:

```
report.md        the report (below); always present
event.json       the scrubbed tracker event, when there is one
request.har      the sanitized HAR, trimmed to the requests that matter
*.png            screenshots, when given
```

`report.md`:

```markdown
REPORT: NEW | DUPLICATE <report-id or job-id> | REGRESSION <job-id>

# <ErrorType>: <normalized message>

| Field        | Value                                            |
| ------------ | ------------------------------------------------ |
| fingerprint  | <8 hex chars>                                    |
| severity     | critical / high / medium / low                   |
| level        | fatal / error / warning                          |
| environment  | production                                       |
| release      | <git sha or version the error happened on>       |
| seen         | first <ISO time>, last <ISO time>, <n> events, <n> users |
| where        | <route or endpoint>, <browser / os / runtime>    |
| trace id     | <id, when there is one>                          |
| tracker      | <adapter name> <issue id>, or "none"             |
| source       | <issue URL, file path, or "reported by a human">  |

## Error
Type, message and stack trace, in-app frames first, as `path:line function`.

## Breadcrumbs
The last events before the error, oldest first: time, category, what happened.

## Failing request
From the HAR or event: method, URL, status, timing, and scrubbed excerpts of the
request and response bodies (2 KB at most each).

## Reproduction
Numbered steps. Mark each step *observed* (it's in the breadcrumbs or HAR) or
*inferred*.

## Redactions
What was scrubbed, and anything dropped because it couldn't be scrubbed safely.
```

### Severity

- **critical**: crash or fatal level, data loss or corruption, payments or
  sign-in broken, or more than 1% of sessions affected.
- **high**: a core flow is blocked for some users, with no workaround.
- **medium**: degraded behaviour with a workaround, or a non-core flow broken.
- **low**: cosmetic, rare, or noise that should be filtered at the source.

### Scrubbing

HARs and events carry live sessions. After Okta's 2023 support breach,
attackers reused session tokens taken from uploaded HAR files. Replace these
with `[Filtered]`:

- headers `Authorization`, `Cookie`, `Set-Cookie`, `Proxy-Authorization`, and any
  header whose name contains `token`, `key`, `secret`, `session`, `auth` or
  `csrf`;
- query parameters and JSON fields named like `token`, `access_token`,
  `id_token`, `refresh_token`, `code`, `state`, `key`, `signature`, `password`,
  `secret`;
- anything shaped like a JWT (`eyJ…`), a bearer token, an API key, or a card
  number;
- emails, phone numbers, names and addresses, replaced with `[email]`,
  `[phone]` and so on; user ids replaced with a short stable hash, so the
  number of affected users still counts.

Drop what you can't scrub with confidence, such as large response bodies and
binary content, and list it under Redactions.
