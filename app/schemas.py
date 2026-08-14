"""Pydantic request and response models for the expenses API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExpenseCreate(BaseModel):
    """Payload to submit a new expense."""

    description: str = Field(min_length=1)
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    category: str = Field(min_length=1)
    submitted_by: str = Field(min_length=1)

    @field_validator("currency")
    @classmethod
    def currency_is_letter_code(cls, value: str) -> str:
        """Reject currency codes that aren't 3 alphabetic characters, uppercasing the rest."""
        if not value.isalpha():
            raise ValueError("currency must be a 3-letter alphabetic code")
        return value.upper()


class ExpenseOut(BaseModel):
    """An expense as returned by the API, including its INR conversion and status."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    description: str
    amount_minor: int
    currency: str
    category: str
    submitted_by: str
    amount_base_minor: int
    fx_rate: float
    status: str
    created_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    comment: str | None


class ExpenseStatusUpdate(BaseModel):
    """Payload to approve or reject a pending expense."""

    status: Literal["approved", "rejected"]
    decided_by: str = Field(min_length=1)
    comment: str | None = None
