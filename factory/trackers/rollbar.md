# Tracker: rollbar

Rollbar, through its REST API v1.

Endpoints follow Rollbar's API as of 2026. If a call returns 404 or an
unexpected shape, check the current API reference before working around it.

## Configuration

```markdown
- Tracker: rollbar
- Base URL: https://api.rollbar.com
- Project: <account>/<project>
- Auth: $ROLLBAR_READ_TOKEN, $ROLLBAR_WRITE_TOKEN   # project access tokens; write only for resolve
```

Calls send `X-Rollbar-Access-Token` with the read token, or the write token for
`resolve`.

## Recognising a source

- `https://app.rollbar.com/a/<account>/fix/item/<project>/<counter>`: an item
  (an issue, in the factory's terms), by its project counter.
- The same URL followed by `/occurrence/<occurrence-id>`: one occurrence.

## fetch

```bash
curl -sS -H "X-Rollbar-Access-Token: $ROLLBAR_READ_TOKEN" \
  "<base>/api/1/item_by_counter/<counter>"          # gives the item id
curl -sS -H "X-Rollbar-Access-Token: $ROLLBAR_READ_TOKEN" \
  "<base>/api/1/item/<item-id>/instances?page=1"     # occurrences, newest first
```

Mapping: item `title` → title; item `id` → group id; item `level` → level;
`first_occurrence_timestamp`, `last_occurrence_timestamp`,
`total_occurrences`, `unique_occurrences` → seen; occurrence `data.body.trace`
or `trace_chain` (`exception`, `frames[]` with `filename`, `lineno`, `method`) →
Error; `data.body.telemetry` → Breadcrumbs; `data.request` → Failing request;
`data.environment` → environment; `data.code_version` → release.

## list

```bash
curl -sS -G -H "X-Rollbar-Access-Token: $ROLLBAR_READ_TOKEN" "<base>/api/1/items" \
  --data-urlencode "status=active" --data-urlencode "environment=<production environment>"
```

Keep the items whose `last_occurrence_timestamp` is after the last poll.

## comment

Not supported by this adapter. Treat `On merge: comment` as `nothing` and say so.

## resolve

```bash
curl -sS -X PATCH -H "X-Rollbar-Access-Token: $ROLLBAR_WRITE_TOKEN" -H "Content-Type: application/json" \
  "<base>/api/1/item/<item-id>" -d '{"status": "resolved", "resolved_in_version": "<merge commit>"}'
```

Rollbar reactivates the item if it happens again in a later version.
