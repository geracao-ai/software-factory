# Tracker: bugsnag

Bugsnag (SmartBear Insight Hub), through its Data Access API.

Endpoints follow the Data Access API v2 as of 2026. If a call returns 404 or an
unexpected shape, check the current API reference before working around it.

## Configuration

```markdown
- Tracker: bugsnag
- Base URL: https://api.bugsnag.com
- Project: <project-id>
- Auth: $BUGSNAG_TOKEN                 # a personal auth token
```

Every call sends `Authorization: token $BUGSNAG_TOKEN` and `X-Version: 2`.

## Recognising a source

- `https://app.bugsnag.com/<org>/<project>/errors/<error-id>`: an error (an
  issue, in the factory's terms).
- The same URL with `?event_id=<event-id>`: one event of it.

## fetch

```bash
curl -sS -H "Authorization: token $BUGSNAG_TOKEN" -H "X-Version: 2" \
  "<base>/projects/<project-id>/errors/<error-id>"
curl -sS -H "Authorization: token $BUGSNAG_TOKEN" -H "X-Version: 2" \
  "<base>/projects/<project-id>/errors/<error-id>/latest_event"   # or /events/<event-id>
```

Mapping: error `error_class` and `message` → title; error `id` → group id;
`severity` → level; `first_seen`, `last_seen`, `events`, `users` → seen; event
`exceptions[].stacktrace[]` (`file`, `line_number`, `method`, `in_project`) →
Error; event `breadcrumbs[]` → Breadcrumbs; event `request` → Failing request;
event `app.release_stage` → environment; event `app.version` → release.

## list

```bash
curl -sS -G -H "Authorization: token $BUGSNAG_TOKEN" -H "X-Version: 2" \
  "<base>/projects/<project-id>/errors" \
  --data-urlencode "filters[error.status][][value]=open" \
  --data-urlencode "filters[app.release_stage][][value]=<production environment>" \
  --data-urlencode "filters[event.since][][value]=<since>" \
  --data-urlencode "sort=last_seen"
```

## comment

`POST <base>/projects/<project-id>/errors/<error-id>/comments` with
`{"message": "<note>"}`.

## resolve

`PATCH <base>/projects/<project-id>/errors/<error-id>` with
`{"operation": "fix"}`. Bugsnag reopens it if it happens again in a later
version.
