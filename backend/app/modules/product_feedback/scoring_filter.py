"""
Module: modules.product_feedback.scoring_filter

The request lists' "Unscored" filter: `scored=unscored|scored` against a scoring model, and
`missing_axis=<key>` to find who lacks one criterion (`missing_axis=any`: who lacks at least one, so is not fully
rated). Shared by both list endpoints, the record-table export and the MCP list tools (through
`service.filter_requests`), so the same rows come back everywhere.

A request is unscored under a model when it has no level on one of the model's *manual* axes (multiplied or
divisor); a derived axis (Demand) is never missing, since a value always falls in a level. The test reads the
per-axis score rows of the candidates' current versions in one statement, so it costs the same for ten requests
as for ten thousand and never depends on how a page was cut.

Dependencies: `models.py`, `scoring.py`, `services.scoring`.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.product_feedback.models import EnhancementRequest, EnhancementRequestVersion, EnhancementRequestVersionScore
from app.modules.product_feedback.scoring import REQUEST_SCORING_SCHEME
from app.services.scoring import resolve_effective_model
from app.services.scoring_custom import effective_scheme

ScoredFilter = Literal["scored", "unscored"]

#: `missing_axis` value meaning "lacks at least one manual criterion of the scheme", rather than one named axis.
ANY_AXIS = "any"


def keep_by_scoring(
    db: Session, organization_id: uuid.UUID, project_id: uuid.UUID | None, requests: list[EnhancementRequest], *,
    scored: ScoredFilter | None, missing_axis: str | None, model_keys: Sequence[str] | None,
) -> list[EnhancementRequest]:
    """The requests whose scoring state matches the filters, in their given order.

    Args:
        db: Active session (read only).
        organization_id: The owning organisation.
        project_id: The project the requests belong to, or `None` for the organisation's inbox.
        requests: Candidate requests of that one owner.
        scored: Keep only requests scored (or not) under the model.
        missing_axis: Keep only requests with no level on this scheme axis (none, for a derived axis), or, for
            `ANY_AXIS`, those with no level on at least one of the scheme's manual axes.
        model_keys: The models chosen when viewing; the first decides `scored`. `None` = the effective default.

    Raises:
        HTTPException: 400 for an unknown model or axis.
    """
    if not requests or (scored is None and missing_axis is None):
        return requests
    scheme = effective_scheme(db, organization_id, REQUEST_SCORING_SCHEME, project_id)
    if missing_axis is not None and missing_axis != ANY_AXIS and scheme.axis(missing_axis) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown scoring axis '{missing_axis}'.")
    model_key = model_keys[0] if model_keys else resolve_effective_model(db, organization_id, scheme, project_id)[0]
    model = scheme.model(model_key)
    if model is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown scoring model '{model_key}'.")
    needed = {
        key for key in (*model.axis_keys, *model.divisor_axis_keys)
        if (axis := scheme.axis(key)) is not None and axis.derived_source is None
    }
    manual = {a.key for a in scheme.axes if a.derived_source is None}
    if missing_axis == ANY_AXIS:
        wanted = needed | manual
    else:
        wanted = needed | ({missing_axis} if missing_axis else set())
    present: dict[uuid.UUID, set[str]] = defaultdict(set)
    for request_id, axis_key in db.execute(
        select(EnhancementRequestVersion.request_id, EnhancementRequestVersionScore.axis_key)
        .join(EnhancementRequestVersionScore, EnhancementRequestVersionScore.version_id == EnhancementRequestVersion.id)
        .where(
            EnhancementRequestVersion.request_id.in_([r.id for r in requests]),
            EnhancementRequestVersion.valid_to.is_(None), EnhancementRequestVersionScore.axis_key.in_(wanted),
        )
    ):
        present[request_id].add(axis_key)
    kept = []
    for request in requests:
        have = present[request.id]
        if scored is not None and (needed <= have) != (scored == "scored"):
            continue
        if missing_axis == ANY_AXIS:
            if manual <= have:
                continue
        elif missing_axis is not None:
            axis = scheme.axis(missing_axis)
            if axis is not None and (axis.derived_source is not None or missing_axis in have):
                continue
        kept.append(request)
    return kept
