# ExpenseFlow — Handoff

For whoever picks this up next: what it does, how it's put together, and what you need
to know to deploy or operate it. This is a PoC, not a production system — see
[Known limitations](#known-limitations) before treating it as one.

## What it does

ExpenseFlow is an expense submission and approval API with one user journey:

1. Someone submits an expense (`POST /expenses`) in any currency.
2. It's normalised to a base currency (INR) and stored as `pending`.
3. An approver approves or rejects it (`PATCH /expenses/{id}/status`).

A secondary, read-only endpoint (`GET /reports/insights`) summarizes spending patterns
across all expenses using the Claude API. A Streamlit app (`ui/app.py`) provides a thin
UI over the API: a submission form, a table of expenses with approve/reject actions, and
an "insights" button.

There is no auth and no user concept — `submitted_by` / `decided_by` are free-text
strings, not references to a users table.

## How it works

### Request flow

`app/main.py` wires up a FastAPI app with two routers from `app/routes.py`:
`router` (prefix `/expenses`) and `reports_router` (prefix `/reports`). On startup,
`init_db()` (`app/db.py`) creates the SQLite schema if it doesn't exist.

- **`POST /expenses`** — validates the payload against `ExpenseCreate`
  (`app/schemas.py`), builds an `Expense` ORM row, and commits it. FX conversion is
  currently stubbed: `fx_rate = 1.0` always, so `amount_base_minor` always equals
  `amount_minor` regardless of `currency`. There's a `TODO` in `app/routes.py` marking
  where a real rate lookup (via httpx, per the stack) will replace this.
- **`GET /expenses`** — lists expenses newest-first, with optional `status` and
  `category` filters applied as SQL `WHERE` clauses.
- **`GET /expenses/{id}`** — fetch-by-id, `404` if missing.
- **`PATCH /expenses/{id}/status`** — approves/rejects. This is implemented as a single
  conditional `UPDATE ... WHERE id = :id AND status = 'pending'`, not a read-then-write.
  If the update affects zero rows, a follow-up read distinguishes `404` (no such
  expense) from `409` (exists but not pending). This makes the pending→decided
  transition atomic at the DB layer, so two concurrent approve calls (or a retried
  request) can't double-decide an expense.
- **`GET /reports/insights`** — reads every expense, reduces each to
  `{amount_base_minor, category, status}`, and asks Claude (`app/insights.py`) for a
  JSON object with a `summary` string and exactly three `bullets`. On any network, API,
  or JSON-shape failure it retries once, then returns a fixed fallback object — this
  endpoint never raises.

### Data model

Single table, `expenses` (`app/models.py`), with a DB-level `CHECK` constraint
restricting `status` to `pending` / `approved` / `rejected`. Money fields
(`amount_minor`, `amount_base_minor`) are integers, never floats — see
[ADR 0001](adr/0001-money-as-integer-minor-units.md) for why. `fx_rate` is a float,
kept as an audit trail of the rate used, not as a value anything sums or compares.

### Persistence

SQLAlchemy engine against SQLite, configured entirely by `DATABASE_URL` (see
[Configuration](#configuration)). `init_db()` also does a minimal, additive migration:
if the `expenses` table exists but is missing a column present on the ORM model (today,
just `comment`), it runs `ALTER TABLE ... ADD COLUMN` for that one column. There is no
migration framework (no Alembic) — schema evolution beyond simple additive columns
needs a manual migration or a rebuilt DB file.

## Configuration

Read from the environment (via `python-dotenv`, loaded from a `.env` file in the
working directory):

| Variable | Required | Default | Effect |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes, for `GET /reports/insights` only | none | Used by `app/insights.py` to call the Claude Messages API. If unset, calls fail and that endpoint returns the fallback insight object (it does not crash the app). |
| `DATABASE_URL` | No | `sqlite:///expenseflow.db` | SQLAlchemy engine URL (`app/db.py`). Swapping this to a non-SQLite URL (e.g. Postgres) is untested — the `connect_args={"check_same_thread": False}` engine option is SQLite-specific and would need to change. |

The Streamlit UI additionally reads `API_BASE` (default `http://127.0.0.1:8000`) as a
plain environment variable — not from `.env` — to locate the API.

## Running it

```
python -m uvicorn app.main:app --reload      # API, http://127.0.0.1:8000
streamlit run ui/app.py                      # UI, separate terminal, API must be up
```

Tests: `python -m pytest -q`.

Full setup instructions (including Windows venv setup and exact package list, since
there's no `requirements.txt`/`pyproject.toml` yet) are in the top-level `README.md`.

## What a deployment engineer needs to know

- **State lives in one file.** `expenseflow.db` is a SQLite file in the working
  directory. There's no volume/backup story here — whoever deploys this needs to decide
  where that file lives and how it's backed up, since it's the entire system of record.
- **Single-process assumption.** SQLite plus `check_same_thread=False` works for one
  Uvicorn worker. Running multiple workers/processes against the same file risks
  `database is locked` errors under concurrent writes — this hasn't been load-tested.
  If this needs to scale past a single process, that's a real infra decision (Postgres
  + a real migration tool), not a config flag.
- **No auth.** Any caller can submit, list, or decide any expense. `submitted_by` and
  `decided_by` are trusted free text from the request body — there's no session, token,
  or identity check anywhere. This is fine for a PoC behind a trusted network, not fine
  for anything internet-facing.
- **Secrets.** Only `ANTHROPIC_API_KEY` is a secret today. It must come from the
  environment/`.env`, never be hardcoded, and never be logged (`app/insights.py`'s
  exception logging logs the failure, not the key).
- **The insights endpoint depends on an external API.** `GET /reports/insights` calls
  Anthropic's API on every request — no caching. Expect its latency and availability to
  track Claude's, and expect it to degrade gracefully (fallback text) rather than error,
  by design.
- **FX conversion is not implemented yet.** `amount_base_minor` is not a real INR
  conversion today — it's a straight copy of `amount_minor`. Anyone consuming
  `amount_base_minor` for real financial totals needs to know it's currently a stub, not
  live exchange-rate data. See the `TODO` in `app/routes.py` and the planned design in
  `docs/ARCHITECTURE.md` (§4, decisions 1–2) for what the real implementation is meant
  to do (timeout → `502`, no partial writes, round-half-up rounding).
- **No migration framework.** `init_db()`'s auto-add-column trick only handles simple
  additive schema changes. Anything more structural (renames, type changes, new tables)
  needs a manual, one-off migration against the live `expenseflow.db`.

## Known limitations

- FX conversion is stubbed at 1:1 for every currency (see above).
- No authentication or authorization.
- No migration framework — schema changes beyond additive columns are manual.
- Single SQLite file — not built for concurrent multi-process writes.
- No caching, rate limiting, or retry policy beyond the insights endpoint's built-in
  one-retry-then-fallback behavior.

See `docs/ARCHITECTURE.md` for the full schema reference, endpoint table, and the
reasoning behind specific edge-case decisions (concurrent approve/reject, planned FX
failure handling, rounding).
