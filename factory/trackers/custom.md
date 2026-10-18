# Tracker: custom

For a project without a vendor: errors go to its own endpoint, a log store, or
an OpenTelemetry backend, and AGENTS.md says how to read them. Copy this file
to `factory/trackers/<name>.md` when you'd rather keep the details out of
AGENTS.md.

## Configuration

```markdown
- Tracker: custom
- Base URL: https://api.example.com
- Project: web-app
- Auth: $ERRORS_API_TOKEN
- fetch: GET <base>/internal/errors/<id> returns one error group with its latest event
- list: GET <base>/internal/errors?status=open&since=<ISO time>
- comment: none
- resolve: PATCH <base>/internal/errors/<id> {"status": "resolved", "release": "<sha>"}
```

Each operation line gives the call and what it returns. Leave out the optional
ones the project doesn't have (`list`, `comment`, `resolve`); `fetch` is
required.

## Recognising a source

Whatever the `fetch` line's id is: a bare id, or a URL that contains it.

## fetch

Make the call the `fetch` line gives. Map the response onto the report format
in `factory/telemetry.md` by field meaning (error type, message, stack frames,
breadcrumbs, request, release, environment, first/last seen, counts, group id),
and write `unknown` for anything the response doesn't carry.

If the project's errors only live in logs (Loki, CloudWatch, Elasticsearch),
the `fetch` line names the query to run, and the group id is the fingerprint
the reporter computes.

## list, comment, resolve

As the configuration lines say. An operation without a line is unsupported:
`list` then fails with that message, and `On merge` falls back to `nothing`.
