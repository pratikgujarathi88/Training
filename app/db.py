"""SQLAlchemy engine, session factory, and FastAPI DB dependency for ExpenseFlow."""

import os
from collections.abc import Generator

from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

load_dotenv()

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///expenseflow.db")

engine: Engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal: sessionmaker[Session] = sessionmaker(
    bind=engine, autocommit=False, autoflush=False
)


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


def get_db() -> Generator[Session, None, None]:
    """Yield a database session for a single request, closing it afterward."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables registered on Base if they don't already exist.

    Also adds any columns present on the ORM model but missing from an
    already-existing SQLite file, so schema additions don't require
    dropping and recreating expenseflow.db.
    """
    Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    if "expenses" in inspector.get_table_names():
        existing_columns = {col["name"] for col in inspector.get_columns("expenses")}
        if "comment" not in existing_columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE expenses ADD COLUMN comment TEXT"))
