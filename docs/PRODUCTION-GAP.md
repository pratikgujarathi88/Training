# ExpenseFlow — Production Readiness Gap Audit

ExpenseFlow is currently a PoC (per `CLAUDE.md`): no auth, one SQLite file, no tests
directory, no deployment tooling. This audits it against a production bar across ten
dimensions, based on the actual code in `app/`, `ui/`, and the repo root — not on what
the brief implies should exist.

Classification:
- **Blocking** — must be closed before this handles real users, real money, or is
  exposed outside a fully trusted network.
- **Deferrable** — safe to ship without, for a controlled/internal rollout, but should
  be tracked and closed before wider exposure.

---

## 1. Authentication and key rotation

**Gap:** There is no authentication anywhere in the API. Every route in
`app/routes.py` (`POST /expenses`, `GET /expenses`, `GET /expenses/{id}`,
`PATCH /expenses/{id}/status`, `GET /reports/insights`) is open to any caller who can
reach the host. `submitted_by` and `decided_by` are free-text fields taken as-is from
the request body (`app/schemas.py`) — nothing verifies the caller is who they claim to
be. There is no concept of a user, session, or API key in the schema or dependencies.
The only credential in the system, `ANTHROPIC_API_KEY`, is read once at call time
(`app/insights.py`) from the environment with no rotation mechanism — rotating it means
editing `.env` and restarting the process.

**Blocking.** Anyone who can approve/reject expenses can approve their own or forge
`decided_by`; anyone can read every expense's data. This is unacceptable for anything
beyond a fully trusted, private-network PoC.

**Effort:** Medium–large. Minimum viable: an API-key or bearer-token dependency
(`Depends`) gating all routes, plus a `decided_by`/`submitted_by` derived from the
authenticated identity rather than the request body (schema and route signature
changes). Full solution (real user accounts, roles distinguishing submitter from
approver, session/token issuance and expiry, key rotation tooling) is 1–2+ weeks.

## 2. Input validation

**Gap:** Mostly solid at the field level — `ExpenseCreate` (`app/schemas.py`) enforces
non-empty strings, `amount_minor > 0`, and a 3-letter alphabetic `currency` code
(uppercased). `ExpenseStatusUpdate.status` is a `Literal["approved", "rejected"]`, so
invalid status values are rejected by pydantic before the route body runs. Gaps:
- `currency` is checked for shape (3 letters) but not validated against a real ISO 4217
  list — `"ZZZ"` passes validation and would silently succeed through the FX stub.
- `category` and `description` have no max length, so unbounded strings can be stored.
- `GET /expenses` query params `status` and `category` are untyped (`str | None`) — an
  invalid `status` value (e.g. `?status=bogus`) is accepted and just matches zero rows,
  rather than returning a `422`.
- No request body size limit is configured anywhere (FastAPI/Uvicorn defaults apply).

**Deferrable**, but low-effort enough that most of it is worth doing before real use:
the current validation prevents the obviously bad cases (negative/zero amounts,
malformed currency shape, invalid status transitions via body). The remaining gaps are
data-quality and abuse-surface issues, not integrity holes, given there's no auth
distinguishing trusted from untrusted callers yet anyway.

**Effort:** Small. Add `max_length` to `description`/`category`, validate `status`/
`category` query params against known enums (`Literal` or a lookup against distinct
category values), and validate `currency` against an ISO 4217 set. A day or so.

## 3. Rate limiting

**Gap:** None exists. No middleware, no per-IP/per-key throttling, nothing in
`app/main.py` beyond router registration and the startup hook. Every endpoint,
including `GET /reports/insights` (which makes an external Claude API call on every
request, with no caching — see `app/insights.py`), can be called as fast as a client
can send requests.

**Blocking** for anything internet-facing or multi-tenant: `GET /reports/insights` has
no caching and a rate-limit-free amplification path to a paid external API. Even for an
internal deployment, unbounded write load on a single SQLite file is a real risk (see
§6). **Deferrable only** if the deployment is genuinely single-team, trusted, and low
volume in the near term.

**Effort:** Small–medium. A basic per-IP or per-key limiter (e.g. `slowapi` or hand-
rolled middleware) covering all routes is a day or two. Caching `GET /reports/insights`
(even a simple TTL cache keyed on the expense set) meaningfully reduces the urgency on
that specific endpoint and is comparably small effort.

## 4. Observability and logging

**Gap:** `app/insights.py` is the only module that logs anything (`logger.exception`/
`logger.warning` around the Claude API call), and does so with the standard library's
default (unconfigured) logging setup — no log level, format, or destination is set
anywhere, so these emit with whatever default `logging` falls back to. Nothing logs
requests, response codes, latency, or the identity of who submitted/decided an expense
(beyond what's stored in the DB row itself). There are no metrics (request counts,
latencies, error rates), no tracing, and no structured logging. If something goes wrong
in production, the only diagnostic surface is whatever reaches stdout by accident plus
the DB rows themselves.

**Blocking.** Operating this without any request-level logging or metrics means
incidents are debugged blind — no way to answer "who approved this," "why did this
request fail," or "is this endpoint slow" without reading DB state after the fact.

**Effort:** Medium. Structured logging middleware (request id, method, path, status,
latency) plus explicit `logging.basicConfig`/structured logger setup is a few days.
Metrics/tracing (Prometheus, OpenTelemetry) integration is another few days to a week
depending on the target stack.

## 5. Error handling

**Gap:** Route-level error handling is reasonable within its scope:
`GET /expenses/{id}` and the decide flow correctly distinguish `404` (not found) from
`409` (wrong state) (`app/routes.py`, `_decide_expense`), and `app/insights.py` never
lets a Claude API failure propagate — it catches broadly, retries once, and falls back
to a fixed object. Gaps:
- There is no global exception handler in `app/main.py`. An unexpected exception
  anywhere else (e.g. a DB connectivity failure, an unhandled `ValueError`) falls
  through to FastAPI's default `500` handler, which by default can leak a stack trace
  depending on how Uvicorn is run (`--reload`/debug-ish setups are more permissive).
- `app/insights.py` catches bare `Exception` (line ~113), which is intentional for
  "never raise" but also silently swallows programming errors (e.g. a typo'd attribute
  access), not just expected network/API failures — those would only surface via logs,
  and logging isn't configured (§4).
- No handling for DB-layer errors (e.g. constraint violations manifesting as raw
  SQLAlchemy exceptions rather than clean 4xx responses) outside the one atomic
  update in `_decide_expense`.

**Deferrable** for the specific gaps (global handler, narrower exception scope in
insights.py) given the two real user-facing flows already fail safely; **blocking** on
the "no global handler / stack traces on 500" point specifically, since that's a direct
information-disclosure risk (§10).

**Effort:** Small. A global exception handler in `app/main.py` that logs full detail
server-side and returns a generic `500` body to the client is under a day.

## 6. Database migrations and pooling

**Gap:** No migration framework (no Alembic or equivalent). `init_db()` (`app/db.py`)
calls `Base.metadata.create_all()` and then does one hand-rolled additive migration —
checking whether the `comment` column exists and running `ALTER TABLE ... ADD COLUMN`
if not. This only handles "one new nullable column"; it has no story for renames, type
changes, new constraints, backfills, or rollback. There's no schema version tracking at
all, so there's no way to know what state a given `expenseflow.db` is in beyond
inspecting its columns.

On pooling: the engine is created via
`create_engine(DATABASE_URL, connect_args={"check_same_thread": False})` with no pool
configuration. For SQLite this mostly doesn't matter (SQLite has no real server-side
connection pool to tune), but it also means the code has no pooling story at all for
the day `DATABASE_URL` points at Postgres or another server-based DB — no `pool_size`,
`max_overflow`, or `pool_pre_ping` is configured anywhere, and switching databases would
require revisiting `connect_args` too (it's SQLite-specific).

**Blocking** before any real schema evolution happens against data anyone depends on —
today, a bad migration means either hand-editing the file or `DROP`/recreate, which
loses data. **Deferrable** on pooling specifically, as long as this stays on SQLite.

**Effort:** Medium. Introducing Alembic (or similar) — initial revision matching the
current schema, wiring `env.py`, replacing `init_db()`'s ad hoc column-add — is roughly
2–4 days including testing against an existing `expenseflow.db`. Pooling config is only
relevant (and cheap, ~half a day) once/if a server-based DB is adopted.

## 7. Secrets management

**Gap:** `ANTHROPIC_API_KEY` is loaded via `python-dotenv` from a `.env` file
(`app/insights.py`, `app/db.py`). This is fine for local dev but is the entire secrets
story — there's no integration with a secrets manager (Vault, AWS/GCP secrets manager,
etc.), no enforcement that `.env` isn't committed (no `.gitignore` exists in the repo
root at all, for `.env` or anything else), and no rotation tooling (rotating the key
means manually editing `.env` and restarting the process — same gap noted in §1). If
`DATABASE_URL` were ever set to a credentialed connection string (e.g. Postgres with a
password embedded), it would be handled the same way — plain environment variable, no
secret-store indirection.

**Blocking**, specifically the missing `.gitignore`: without one, `.env` (or an
accidentally-committed `expenseflow.db` containing real expense data) has no guardrail
against being committed to version control. That's a straightforward, cheap fix.
The lack of a secrets-manager integration is **deferrable** for a small/internal
deployment using environment-injected secrets (e.g. via the deployment platform), as
long as `.env` itself never ends up in the repo or in logs.

**Effort:** Trivial for the `.gitignore` fix (minutes). Small–medium for a secrets
manager integration if required by the target environment (1–3 days, mostly wiring and
IAM/permissions setup, not code volume).

## 8. Tests and coverage

**Gap:** There is no `tests/` directory and no test files anywhere in the repo (a
`.pytest_cache/` exists, meaning pytest has been run before, but no test files remain in
the tree). `CLAUDE.md` documents `python -m pytest -q` as the test command, but running
it today collects zero tests. There is no coverage tooling configured, and no CI
workflow (no `.github/workflows` or equivalent) running tests automatically.

**Blocking.** Zero test coverage on money-handling, state-transition, and validation
logic (exactly the kind of logic where an unnoticed regression is expensive) is not
acceptable at a production bar, independent of how good the current code looks on
inspection.

**Effort:** Medium. Given FastAPI's `TestClient` and the existing route/schema
structure, a first meaningful suite — expense creation/validation edge cases, the
`404`/`409` decide-flow branches, list filters, and mocking the Claude call in
`insights.py` — is roughly 3–5 days to get solid coverage on `app/`. CI wiring to run it
automatically is another small task (~half a day) once tests exist.

## 9. Deployment and health checks

**Gap:** No health/readiness endpoint exists (`grep` across `app/` for anything like
`/health`, `/ping`, liveness/readiness confirms none). No Dockerfile, no process
manager config (e.g. gunicorn/uvicorn worker config for production, systemd unit), and
no CI/CD configuration anywhere in the repo. The documented run command
(`uvicorn app.main:app --reload`) is a dev-mode invocation (`--reload` is not intended
for production use — it adds file-watching overhead and is typically paired with debug
behavior). There's no documented production process (worker count, restart policy,
graceful shutdown behavior for in-flight requests against the single SQLite file).

**Blocking.** Without a health check, no load balancer, orchestrator, or uptime monitor
can tell if the service is actually serving traffic versus just running; without any
deployment artifact (Dockerfile, process config), "deploying this" today means manually
running the dev command on a box.

**Effort:** Medium. A `GET /health` endpoint (checking DB connectivity at minimum) is
trivial (a couple hours). A Dockerfile plus a production-appropriate run command
(uvicorn without `--reload`, explicit worker count, or a WSGI/ASGI process manager) is
half a day to a day. Full CI/CD (build, test, deploy pipeline) is a separate, larger
effort depending on target infra — plan for a few days.

## 10. Data privacy for expense data

**Gap:** Expense rows include free-text `description`, `submitted_by`, `decided_by`,
and `comment` — plausibly personal or sensitive data (who spent money on what, and who
approved it) with no privacy controls: no encryption at rest (plain SQLite file on
disk), no field-level redaction in logs (moot today since there's effectively no
request logging — see §4, but a risk the moment logging is added if done carelessly),
no data-retention or deletion policy, and no access control (§1) restricting who can
read whose expenses. `GET /reports/insights` additionally sends every expense's
`amount_base_minor`, `category`, and `status` to a third-party API (Claude) with no
opt-out, minimization beyond those three fields, or documented data-processing
agreement consideration — worth confirming this is acceptable for whatever data
sensitivity level real expense data carries at this organization.

**Blocking** before handling real (non-synthetic) expense data: no access control (§1)
combined with no encryption at rest and no retention policy is a straightforward
compliance/privacy gap for anything containing real names and spending data. The
third-party data flow to Claude is **deferrable-with-a-decision** — it's already
minimized to non-identifying fields (no `description`, no `submitted_by`), so the main
action item is confirming that's an acceptable data flow, not necessarily changing the
code.

**Effort:** Medium, and mostly organizational rather than code: encryption at rest
depends on the deployment target (managed DB encryption, or disk-level encryption for
the SQLite file) — small if the platform provides it, larger if not. A retention/
deletion policy is a decision plus a small script/endpoint, not a redesign (~1-2 days
once the policy is decided). Confirming the Claude data flow is acceptable is a
conversation, not an engineering task.

---

## Summary

| # | Area | Status | Rough effort |
|---|---|---|---|
| 1 | Authentication and key rotation | Blocking | Medium–large (1–2+ weeks) |
| 2 | Input validation | Deferrable (partially in place) | Small (~1 day) |
| 3 | Rate limiting | Blocking (internet-facing) | Small–medium (1–2 days) |
| 4 | Observability and logging | Blocking | Medium (few days–1 week) |
| 5 | Error handling | Mostly deferrable; global handler blocking | Small (<1 day) |
| 6 | DB migrations and pooling | Blocking (migrations); pooling deferrable | Medium (2–4 days) |
| 7 | Secrets management | Blocking (`.gitignore`); rest deferrable | Trivial–small |
| 8 | Tests and coverage | Blocking | Medium (3–5 days + CI) |
| 9 | Deployment and health checks | Blocking | Medium (few days) |
| 10 | Data privacy for expense data | Blocking (real data); Claude flow deferrable | Medium (mostly organizational) |

None of these gaps are surprising for a stated PoC — `CLAUDE.md` is explicit that this
is not production code. This audit exists to make the distance to a production bar
concrete before real users or real expense data touch it.
