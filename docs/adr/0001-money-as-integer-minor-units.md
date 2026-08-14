# 1. Money as integer minor units

## Status

Accepted

## Context

ExpenseFlow stores and compares monetary amounts: the amount an expense was submitted
for (`amount_minor`, in its original `currency`) and its converted value in the base
currency (`amount_base_minor`, in INR). These values are written once, read back
verbatim in API responses, and — once real FX conversion and any future reporting/sums
are implemented — will be added and compared across expenses.

Floating-point types (`float`/`double`) cannot represent most decimal fractions (e.g.
`0.10`) exactly in binary. Repeated arithmetic on floats accumulates rounding error, and
independently-computed float amounts can compare unequal despite being "the same" money
value. For a system whose entire purpose is tracking money accurately, that's a direct
correctness risk, not a cosmetic one.

## Decision

Store every monetary amount as an integer number of minor units (paise for INR, cents
for USD, etc.) — never as a float. This is a project-wide convention (stated in
`CLAUDE.md`): `amount_minor` and `amount_base_minor` are both `INTEGER` columns
(`app/models.py`), validated as `int` in `ExpenseCreate`/`ExpenseOut`
(`app/schemas.py`), and `ExpenseCreate.amount_minor` is constrained to `> 0`.

`fx_rate` is the one deliberate exception: it's stored as a float because it isn't
itself a monetary amount, it's an audit record of the rate used for a conversion, kept
so the conversion is reproducible/explainable later.

## Alternatives considered

- **Float/double dollars (or rupees).** Rejected: exact decimal fractions like `0.10`
  aren't representable in binary floating point, so sums and comparisons drift. This is
  the standard, well-documented failure mode floats have for money and is exactly what
  the integer-minor-units convention exists to avoid.
- **Decimal type (e.g. Python's `decimal.Decimal`, or a DB `NUMERIC`/`DECIMAL` column).**
  Avoids the binary-fraction problem, but still requires a rounding/precision policy per
  currency, adds a type that needs explicit (de)serialization through JSON (Pydantic/
  FastAPI don't map `Decimal` to a plain JSON number by default), and is heavier than
  needed for a PoC with one currency-conversion boundary. Integers plus a documented
  minor-unit convention give the same exactness with a plain `int` end-to-end.
- **String-encoded amounts** (e.g. `"45.00"`). Rejected: pushes parsing and arithmetic
  onto every consumer of the API, and still needs a decision procedure for rounding —
  it just moves the problem instead of solving it.

## Consequences

- Every amount in the API (`amount_minor`, `amount_base_minor`) is an integer count of
  the smallest unit of its currency. A UI or client must divide by 100 (for currencies
  with 2 decimal minor units, which is what this codebase assumes) to display a decimal
  amount — see `_format_minor` in `ui/app.py` for the reference implementation
  (`amount_minor / 100`, formatted to two decimal places).
- `ExpenseCreate.amount_minor` must be a positive integer number of minor units at the
  API boundary; callers submitting a decimal major-unit amount (e.g. a UI form taking
  rupees) are responsible for converting to minor units before calling the API, exactly
  as `ui/app.py` does (`round(amount * 100)`).
- Real FX conversion (not yet implemented — see the `TODO` in `app/routes.py`) must
  produce `amount_base_minor` as an integer. `docs/ARCHITECTURE.md` (§4, decision 2)
  already commits to the specific rule for that: round-half-up to the nearest integer
  minor unit, applied in exactly one place, so rounding is consistent and sums of
  approved expenses reconcile.
- This convention assumes every currency handled has exactly two decimal digits in its
  minor unit (cents/paise). Currencies with different minor-unit precision (e.g. JPY,
  which has none) aren't accounted for yet and would need an explicit per-currency
  decision if support for them is ever added.
