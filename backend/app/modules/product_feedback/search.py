"""
Module: modules.product_feedback.search

The `ArtefactSearchProvider` for the `enhancement_request` artefact type, so the global search finds requests
by code, title, tags and the request's descriptive text.

Responsibilities:
- Declare the columns the search reads (from the request's current version) and the free-text fields it may match.

Design decisions:
- Opt-in fields: the description only. The decline reason and change notes are not matched.
- An organisation's inbox request is found only where the `organization_requests` sub-component is on
  (`organization_subcomponent`), and opens on the organisation's inbox page.

Dependencies: this module's models and labels; `services.search_core` (builders).
"""

from __future__ import annotations

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
        fields=(SearchField("description", "Description", EnhancementRequestVersion.description),),
    ),
}
