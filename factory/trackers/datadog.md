# Tracker: datadog

Datadog Error Tracking: RUM for browser errors, APM and logs for backend ones.

If the session has a Datadog MCP tool, prefer it for every operation. Otherwise
use the HTTP API below, which follows Datadog's v2 API as of 2026. Error
Tracking endpoints have changed between versions: if a call returns 404 or an
unexpected shape, check the current API reference before working around it.

## Configuration

```markdown
- Tracker: datadog
- Base URL: https://api.datadoghq.com  # or api.datadoghq.eu, api.us5.datadoghq.com, ...
- Project: service:<service-name>      # the service tag errors carry
- Auth: $DD_API_KEY, $DD_APP_KEY       # app key scope: error_tracking_read (+ write for resolve)
```

Every call sends `DD-API-KEY: $DD_API_KEY` and `DD-APPLICATION-KEY: $DD_APP_KEY`.

## Recognising a source

- `https://app.datadoghq.com/error-tracking?...&issueId=<issue-id>` (or the
  regional `app.` host): an issue.
- `https://app.datadoghq.com/rum/sessions?...event=<event-id>` or an APM trace
  URL: one event; read it with the RUM or spans search below.
- A UUID: an issue id.

## fetch

1. The issue:
   `GET <base>/api/v2/error-tracking/issues/<issue-id>` gives the error type,
   message, first/last seen, the representative stack, and its state.
2. Its latest occurrence: search RUM events for browser errors, or logs/spans
   for backend ones, filtered by the issue:
   ```bash
   curl -sS -X POST -H "DD-API-KEY: $DD_API_KEY" -H "DD-APPLICATION-KEY: $DD_APP_KEY" \
     -H "Content-Type: application/json" "<base>/api/v2/rum/events/search" \
     -d '{"filter": {"query": "@issue.id:<issue-id> env:<production environment>", "from": "now-7d"},
          "sort": "-timestamp", "page": {"limit": 1}}'
   ```
   For backend errors use `/api/v2/logs/events/search` with the same query.
3. For a browser error, the RUM session's events before the error are the
   breadcrumbs: search RUM events with `@session.id:<session id>` and type
   `view`, `action`, `resource` or `error`, up to the error's timestamp.

Mapping: `error.type`, `error.message` and `error.stack` → Error; `version` →
release; `env` → environment; `view.url` or `http.url_details.path` → where;
`trace_id` or `_dd.trace_id` → trace id; the issue id → group id.

## list

`POST <base>/api/v2/error-tracking/issues/search` with a query on
`service:<service-name> env:<production environment>`, the time range since the
last poll, and the issue states `OPEN` and `FOR_REVIEW`.

## comment

Not supported by this adapter. Treat `On merge: comment` as `nothing` and say so.

## resolve

Set the issue's state to `RESOLVED` with the Error Tracking issue state
endpoint (`PUT <base>/api/v2/error-tracking/issues/<issue-id>/state`). Datadog
reopens it as a regression when a newer version raises it again.
