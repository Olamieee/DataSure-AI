# REST API reference (v1)

Base URL: `/api/v1`. All examples assume the app is running at `http://localhost:8000`.

## Authentication

Every request requires one of:

| Method | Notes |
|---|---|
| Browser session cookie | What the web UI uses after login. |
| `X-API-Key: <key>` header | Create labelled, revocable keys on **Settings → API keys**. Only SHA-256 hashes are stored; the raw key is shown exactly once at creation. |

A missing or wrong key returns `401 {"error": "authentication required: send a valid X-API-Key header or log in"}`.

The API is read-mostly by design: it never creates or deletes datasets, has
**no upload endpoint**, and every resource is scoped to the caller —
cross-user access returns `404 {"error": "... not found"}`, identical in shape
to "does not exist", so ids are never enumerable.

## Error shape

- API errors: `{"error": "<human readable message>"}` with an appropriate status (`400` bad input, `401` auth, `404` unknown/unowned, `422` usable data rejected by validation, `503` profiling budget exhausted, `500` unexpected).
- App-level 404s (including unknown `/api/...` paths) include a `request_id` field that is also returned as the `X-Request-ID` response header on every request and appears in server logs for correlation.

## Pagination

List endpoints share this envelope (defaults: 20 per page, maximum 100):

```json
{
  "page": 1, "per_page": 20, "total": 47, "next_page": 2,
  "<resource>": [ ... ]
}
```

`next_page` is `null` on the last page. Pass `?page=N&per_page=M` to navigate. Ordering is stable (`created_at DESC, id DESC`), so pagination never repeats or drops rows.

## Endpoints

### Health

```
GET /healthz                       # unauthenticated, app-level
```
`200 {"status": "ok", "checks": {"database": {"status": "ok", "latency_ms": 0.5}}}` — or `503` with `"status": "degraded"` when the database cannot be reached. Use this for load balancers and uptime monitors.

```
GET /api/v1/health                 # unauthenticated, API-level
```
`200 {"status": "ok", "service": "datasure-ai", "api_version": "v1"}`.

### Datasets

```
GET /api/v1/datasets?page=1&per_page=20
```
Dataset summaries (`id`, `name`, `extension`, `row_count`, `column_count`, `status`, `size_bytes`, `storage_version`, `is_cleaned`, `tags`, `created_at`). `tags` is a list of the dataset's free-form labels (empty list when untagged).

```
GET /api/v1/datasets/<id>
```
Adds `sha256` (content hash), plus `latest_assessment_id` and `latest_quality_score` when an assessment exists.

```
GET /api/v1/datasets/<id>/preview?rows=10
```
First rows as `{columns: [...], rows: [[...], ...]}`. `rows` is capped by the server (`PREVIEW_ROWS`, default 25).

```
GET /api/v1/datasets/<id>/assessments?page=1
GET /api/v1/datasets/<id>/cleaning?page=1
```
Assessment history and the cleaning-operation log, both paginated.

### Assessments

```
POST /api/v1/datasets/<id>/assessments
Content-Type: application/json

{"target_column": "salary", "label": "monthly sync run"}
```
`201` with the assessment summary (`id`, `quality_score`, `scores`, `issues`, `duration_ms`, and more). Fields are optional. `422` when the stored file can no longer be parsed, `503` when the profiling time budget stopped the run.

```
GET /api/v1/assessments/<id>
```
Adds the full `profile` object (column statistics) to the summary shape.

### Assessments — comparisons, columns, exports

```
GET /api/v1/assessments/compare?from=<id>&to=<id>
```
Compares two of your assessments (cross-dataset is allowed as long as both are yours). Returns the same structure the web compare page renders:

```json
{"from": 3, "to": 9, "comparison": {"overall": {"from": 90.5, "to": 87.0, "delta": -3.5}, "verdict": "...", "issues": {"repeated": [], "new": [], "resolved": []}}}
```
`400` for missing or equal ids, `404` for unknown/unowned assessments.

```
GET /api/v1/datasets/<id>/columns
```
Column-level dictionary from the latest assessment's profile: `{dataset_id, assessment_id, row_count, column_count, columns: [...]}`. `404` when no assessment exists yet.

```
GET /api/v1/datasets/<id>/file
```
Downloads the currently stored file (`Content-Disposition: attachment`) — the cleaned version when the dataset has been processed. `404` if the stored file is missing from disk.

```
GET /api/v1/assessments/<id>/export/<kind>.csv
```
CSV export of `issues`, `stats` (per-column statistics) or `history` (per-cleaning-operation rows). `404` for unknown kinds or unowned assessments.

```
GET /api/v1/datasets/<id>/trend
```
Chronological quality trajectory for one dataset: `{dataset_id, points: [{assessment_id, at, quality_score, issue_count}]}` ordered oldest first. `points` is empty before the first assessment. Exports are guarded against CSV formula injection (cells starting with `=`, `+` or `@` get a leading `'`).

### Schema contracts

```
GET /api/v1/contracts?page=1
GET /api/v1/contracts/<id>
```
The list shape has `id`, `name`, `description`, `column_count`, `created_at`; the retrieve shape adds the full `contract` JSON (columns with `name`, `kind`, `nullable`, `allowed_values`).

```
POST /api/v1/contracts/<contract_id>/validate
Content-Type: application/json

{"dataset_id": 7}
```
Runs contract validation against one of your datasets, updates the dataset's stored contract flags (same behaviour as the web flow), and returns:

```json
{
  "contract_id": 1, "contract_name": "people schema",
  "dataset_id": 7, "passed": false,
  "violations": [{"type": "missing_column", "column": "age", "message": "..."}]
}
```
`400` when the body is not JSON with an integer `dataset_id`, `404` for unknown/unowned ids, `422` when the stored file can no longer be parsed.

### Validation rules

Rules are structured definitions with a fixed operator registry — never free-form expressions.

```
GET /api/v1/rules?page=1
```

```
POST /api/v1/rules
Content-Type: application/json

{
  "name": "age bounds",
  "rule_type": "numeric_range",
  "rule": {"column": "age", "min": 0, "max": 130, "inclusive": true}
}
```
`201` with the normalised stored rule. Rule types: `numeric_range`, `allowed_values`, `unique`, `not_null`, `column_comparison`; severity is `"error"` or `"warning"`. Malformed definitions return `422` with the reason (e.g. `operator must be one of ['<', '<=', '!=', ...]`). `400` for a missing name or a non-object `rule`.

```
POST /api/v1/datasets/<id>/rules/run
Content-Type: application/json

{"rule_ids": [3, 4]}
```
Runs each selected rule (all must belong to you) against the dataset and returns one result per rule:

```json
{
  "dataset_id": 7, "passed": 1, "failed": 1,
  "results": [
    {"id": 3, "name": "age bounds", "passed": true, "count": 0,
     "message": "", "examples": [], "severity": "info"}
  ]
}
```
`400` when `rule_ids` is missing or is not a list of integers; `404` when any id does not exist or is not yours; `422` when the stored file can no longer be parsed.

## Example: validate a re-uploaded file end to end

```bash
KEY=...   # from Settings → API keys
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/datasets
curl -s -H "X-API-Key: $KEY" http://localhost:8000/api/v1/contracts
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"dataset_id": 7}' \
  http://localhost:8000/api/v1/contracts/1/validate
```
