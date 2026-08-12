"""
Module: schemas.email

Request model for the "send test email" admin action — shared between the
deployment-wide endpoint (`routers/system.py`) and the organisation-scoped
one for an org with its own SMTP override (`routers/orgs.py`), since both
take the same shape.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr


class TestEmailRequest(BaseModel):
    """Optional override recipient for a test email.

    Attributes:
        to_email: Where to send the test email. When omitted, the calling
            admin's own account address is used.
    """

    to_email: EmailStr | None = None
