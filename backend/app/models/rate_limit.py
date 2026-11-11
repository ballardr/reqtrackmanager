"""
Module: models.rate_limit

`RateLimitBucket`: one token bucket kept in the database so a rate limit holds across every worker and replica
(`services.rate_limit.RateLimiter` with a `shared` name). Rows hold a bucket name, the tokens left and when they were
last refilled; they carry no personal data beyond the key the limiter was given (a client address or an account id),
and idle rows are deleted after a day.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class RateLimitBucket(Base):
    """A token bucket: `bucket` is `<limiter name>:<key>`; `tokens` is the balance at `updated_at` (database time)."""

    __tablename__ = "rate_limit_buckets"

    bucket: Mapped[str] = mapped_column(String(300), primary_key=True)
    tokens: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
