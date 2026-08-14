"""API routes for submitting, listing, and deciding expenses."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.insights import generate_insight
from app.models import Expense
from app.schemas import ExpenseCreate, ExpenseOut, ExpenseStatusUpdate

router = APIRouter(prefix="/expenses", tags=["expenses"])
reports_router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=ExpenseOut, status_code=201)
def create_expense(payload: ExpenseCreate, db: Session = Depends(get_db)) -> Expense:
    """Submit a new expense, normalising its amount to base currency (INR).

    FX conversion is stubbed at 1:1 for now; a real rate lookup will replace
    this once an FX provider is chosen.
    """
    # TODO: look up the real FX rate for payload.currency -> INR here instead
    # of hardcoding 1.0, and use that rate for amount_base_minor below.
    fx_rate = 1.0
    expense = Expense(
        submitted_by=payload.submitted_by,
        description=payload.description,
        amount_minor=payload.amount_minor,
        currency=payload.currency,
        category=payload.category,
        amount_base_minor=payload.amount_minor,
        fx_rate=fx_rate,
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.get("", response_model=list[ExpenseOut])
def list_expenses(
    status: str | None = None,
    category: str | None = None,
    db: Session = Depends(get_db),
) -> list[Expense]:
    """List expenses, most recently created first, optionally filtered by status and/or category."""
    query = select(Expense).order_by(Expense.created_at.desc())
    if status is not None:
        query = query.where(Expense.status == status)
    if category is not None:
        query = query.where(Expense.category == category)
    return list(db.scalars(query))


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(expense_id: int, db: Session = Depends(get_db)) -> Expense:
    """Fetch a single expense by id, or 404 if it doesn't exist."""
    expense = db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense


def _decide_expense(
    expense_id: int, decision: ExpenseStatusUpdate, db: Session
) -> Expense:
    """Apply an approve/reject decision atomically, only if the expense is still pending."""
    result = db.execute(
        update(Expense)
        .where(Expense.id == expense_id, Expense.status == "pending")
        .values(
            status=decision.status,
            decided_by=decision.decided_by,
            comment=decision.comment,
            decided_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    if result.rowcount == 0:
        expense = db.get(Expense, expense_id)
        if expense is None:
            raise HTTPException(status_code=404, detail="Expense not found")
        raise HTTPException(status_code=409, detail="Expense is not pending")

    return db.get(Expense, expense_id)


@router.patch("/{expense_id}/status", response_model=ExpenseOut)
def update_expense_status(
    expense_id: int, payload: ExpenseStatusUpdate, db: Session = Depends(get_db)
) -> Expense:
    """Approve or reject a pending expense.

    404 if the expense doesn't exist, 409 if it's no longer pending.
    """
    return _decide_expense(expense_id, payload, db)


@reports_router.get("/insights")
def get_insights(db: Session = Depends(get_db)) -> dict:
    """Generate three short bullet insights about spending patterns across all expenses."""
    expenses = list(db.scalars(select(Expense)))
    expense_dicts = [
        {
            "amount_base_minor": expense.amount_base_minor,
            "category": expense.category,
            "status": expense.status,
        }
        for expense in expenses
    ]
    return {"insight": generate_insight(expense_dicts)}
