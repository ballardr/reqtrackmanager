"""
Module: modules.product_feedback.search

The `ArtefactSearchProvider` for `enhancement_request`: the columns the search
reads (from the current version) and the opt-in text fields (the description
and external reference keys; not the decline reason, change notes or links).
An inbox request is found only where `organization_requests` is on and opens on
the inbox page. Dependencies: this module's models and labels; `services.search_core`.
"""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.external_reference import ExternalReference
from app.modules.product_feedback.labels import REQUEST_STATUS_LABEL
from app.modules.product_feedback.models import (
    EnhancementRequest,
    EnhancementRequestComment,
    EnhancementRequestVersion,
)
from app.modules.product_feedback.service import ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY
from app.modules.registry import ArtefactSearchProvider, SearchField
from app.services.search_core import comments_of, versioned_provider

SEARCH_PROVIDERS: dict[str, ArtefactSearchProvider] = {
    "enhancement_request": versioned_provider(
        EnhancementRequest, EnhancementRequestVersion, "request_id", title=EnhancementRequestVersion.title,
        status_labels=REQUEST_STATUS_LABEL, organization_subcomponent=ORGANIZATION_REQUESTS_SUBCOMPONENT_KEY,
        comments=comments_of(EnhancementRequestComment, EnhancementRequestComment.request_id),
        fields=(
            SearchField("description", "Description", EnhancementRequestVersion.description, markdown=True),
            # The keys of the request's external references (PROJ-123), so a ticket number finds the request.
            SearchField("references", "External references", select(func.string_agg(
                ExternalReference.key, " ",
            )).where(
                ExternalReference.artefact_type == "enhancement_request", ExternalReference.artefact_id == EnhancementRequest.id,
            ).scalar_subquery()),
        ),
    ),
}
