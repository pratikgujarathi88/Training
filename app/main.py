"""FastAPI application entrypoint for ExpenseFlow."""

from fastapi import FastAPI

from app.db import init_db
from app.routes import reports_router, router

app = FastAPI(title="ExpenseFlow")

app.include_router(router)
app.include_router(reports_router)


@app.on_event("startup")
def on_startup() -> None:
    """Create database tables on application startup if they don't exist."""
    init_db()
