# Tracker: sentry

Sentry, sentry.io or self-hosted. GlitchTip implements most of the same API, so
`Tracker: sentry` works for it too; check `fetch` against your instance once.

Endpoints follow Sentry's public API as of 2026. If a call returns 404 or an
unexpected shape, check the current API reference before working around it.

## Configuration

```markdown
- Tracker: sentry
- Base URL: https://sentry.io          # or https://de.sentry.io, or self-hosted
- Project: <org-slug>/<project-slug>
- Auth: $SENTRY_AUTH_TOKEN             # scopes: event:read; event:write for comment/resolve
```

Every call sends `Authorization: Bearer $SENTRY_AUTH_TOKEN`. `<org>` and
`<project>` come from `Project`.

## Recognising a source

- `https://<org>.sentry.io/issues/<issue-id>/` or
  `<base>/organizations/<org>/issues/<issue-id>/`: an issue.
- Either of those followed by `events/<event-id>/`: one event of that issue.
- A bare number: an issue id.

## fetch

```bash
curl -sS -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "<base>/api/0/organizations/<org>/issues/<issue-id>/"
curl -sS -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" \
  "<base>/api/0/organizations/<org>/issues/<issue-id>/events/latest/"   # or events/<event-id>/
```

Mapping onto the report:

| Report field   | From                                                                  |
| -------------- | --------------------------------------------------------------------- |
| title          | issue `title`                                                         |
| group id       | issue `id`                                                            |
| level          | issue `level`                                                         |
| seen           | issue `firstSeen`, `lastSeen`, `count`, `userCount`                   |
| environment, release | event `tags` (`environment`, `release`)                         |
| where          | event `tags` (`url` or `transaction`, `browser`, `os`, `runtime`)     |
| trace id       | event `contexts.trace.trace_id`                                       |
| Error          | event `entries[type=exception].data.values[]`: `type`, `value`, and `stacktrace.frames[]` (`filename`, `lineNo`, `function`, `inApp`; frames are oldest first, so reverse them) |
| Breadcrumbs    | event `entries[type=breadcrumbs].data.values[]`                       |
| Failing request| event `entries[type=request].data`                                    |

## list

```bash
curl -sS -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" -G \
  "<base>/api/0/projects/<org>/<project>/issues/" \
  --data-urlencode "query=is:unresolved environment:<production environment> lastSeen:>=<since>" \
  --data-urlencode "sort=date"
```

New and regressed issues are both unresolved; the issue's `substatus` says
`new` or `regressed`.

## comment

```bash
curl -sS -X POST -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" -H "Content-Type: application/json" \
  "<base>/api/0/organizations/<org>/issues/<issue-id>/comments/" -d '{"text": "<note>"}'
```

## resolve

```bash
curl -sS -X PUT -H "Authorization: Bearer $SENTRY_AUTH_TOKEN" -H "Content-Type: application/json" \
  "<base>/api/0/organizations/<org>/issues/<issue-id>/" \
  -d '{"status": "resolved", "statusDetails": {"inNextRelease": true}}'
```

Sentry reopens the issue as a regression if it happens on a later release.
