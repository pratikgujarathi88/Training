 # ExpenseFlow

A small expense submission and approval API. This is a PoC, not a production system.

One user journey: submit an expense, convert it to a base currency (INR), approve or
reject it. A secondary read-only endpoint generates spending insights over all expenses
using the Claude API. A Streamlit UI is included as a thin client over the API.

## Stack

- Python 3.12, FastAPI, Uvicorn
- SQLAlchemy ORM on SQLite (file: `expenseflow.db`) for the PoC
- httpx for the external FX rate call (and for the Streamlit UI's HTTP calls)
- pydantic v2 for request and response models
- anthropic (Claude Messages API) for the spending-insights endpoint
- Streamlit for the UI (`ui/app.py`)
- pytest for tests

Money is always stored as integer minor units (paise/cents), never float. Base currency
is INR; amounts are normalised to base on write.

> Note: `POST /expenses` currently stubs FX conversion — `fx_rate` is hardcoded to `1.0`
> and `amount_base_minor` always equals `amount_minor`, regardless of `currency`. There's
> a `TODO` in `app/routes.py` marking where a real rate lookup will replace this.

## Setup on Windows

These steps use `py`, the Python launcher installed with Python on Windows. Run them
from PowerShell or cmd.exe in the project root.

1. Create the virtual environment:

   ```
   py -3.12 -m venv .venv
   ```

2. Activate it:

   ```
   .venv\Scripts\activate
   ```

   (In PowerShell, if activation is blocked by the execution policy, run
   `Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned` first.)

3. Install dependencies:

   ```
   pip install fastapi uvicorn "sqlalchemy>=2.0" httpx "pydantic>=2.0" python-dotenv anthropic streamlit pytest
   ```

No `requirements.txt` or `pyproject.toml` exists in the repo yet, so dependencies are
installed directly by name as above. Do not add further third-party dependencies without
checking with the project owner first.

## Configure `.env`

Create a `.env` file in the project root (it's read via `python-dotenv` and is
git-ignored). Two variables are read from the environment:

| Variable | Required | Default | Used by |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes, for `GET /reports/insights` | none | `app/insights.py`, to call the Claude Messages API |
| `DATABASE_URL` | No | `sqlite:///expenseflow.db` | `app/db.py`, the SQLAlchemy engine |

Example `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
```

The Streamlit UI (`ui/app.py`) also reads `API_BASE` (default `http://127.0.0.1:8000`)
to know where the API is running, but this is a plain environment variable, not one
loaded from `.env`.

## Run

Start the API (creates `expenseflow.db` and its tables on first startup if they don't
exist):

```
python -m uvicorn app.main:app --reload
```

The API is served at `http://127.0.0.1:8000`; interactive docs are at
`http://127.0.0.1:8000/docs`.

Start the Streamlit UI in a separate terminal (with the API already running):

```
streamlit run ui/app.py
```

## Test

```
python -m pytest -q
```

## Endpoint reference

### `POST /expenses`

Submit a new expense. FX conversion is currently stubbed at 1:1 (see the note above).

Request body:

```json
{
  "submitted_by": "jane@company.com",
  "description": "Client dinner",
  "amount_minor": 450000,
  "currency": "usd",
  "category": "meals"
}
```

- `description`: non-empty string.
- `amount_minor`: integer, must be greater than 0.
- `currency`: exactly 3 alphabetic characters; normalised to uppercase.
- `category`: non-empty string.
- `submitted_by`: non-empty string.

Response: `201` with the created expense object (see shape below).

### `GET /expenses`

List expenses, most recently created first. Supports two optional query params, which
can be combined:

- `status` — filter by `pending`, `approved`, or `rejected`.
- `category` — filter by exact category match.

Response: `200` with a JSON array of expense objects.

### `GET /expenses/{expense_id}`

Fetch a single expense by id.

Response: `200` with the expense object, or `404` if no expense with that id exists.

### `PATCH /expenses/{expense_id}/status`

Approve or reject a pending expense. The transition only succeeds if the expense is
currently `pending`.

Request body:

```json
{
  "status": "approved",
  "decided_by": "manager@company.com",
  "comment": "Looks good"
}
```

- `status`: `"approved"` or `"rejected"`.
- `decided_by`: non-empty string.
- `comment`: optional string.

Response: `200` with the updated expense object; `404` if the expense doesn't exist;
`409` if the expense is no longer `pending`.

### `GET /reports/insights`

Generate a short spending-insight summary across all expenses using the Claude API.

Response: `200` with:

```json
{
  "insight": {
    "summary": "short string",
    "bullets": ["short string", "short string", "short string"]
  }
}
```

On any API, network, or parsing failure, this falls back to a safe default (`"Insights
are unavailable right now. Please try again later."`, empty `bullets`) rather than
raising an error.

### Expense object shape

Returned by `POST /expenses`, `GET /expenses`, `GET /expenses/{id}`, and
`PATCH /expenses/{id}/status`:

```json
{
  "id": 1,
  "description": "Client dinner",
  "amount_minor": 450000,
  "currency": "USD",
  "category": "meals",
  "submitted_by": "jane@company.com",
  "amount_base_minor": 450000,
  "fx_rate": 1.0,
  "status": "pending",
  "created_at": "2026-08-11T10:15:00Z",
  "decided_at": null,
  "decided_by": null,
  "comment": null
}
```

## Do not touch

- Do not edit `.venv`, `.git`, or `expenseflow.db` directly.
- Do not add new third-party dependencies without checking with the project owner first.
- Do not invent endpoints that are not in the brief.
