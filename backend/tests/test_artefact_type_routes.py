"""Guard that keeps the frontend's artefact-type route check honest.

`frontend/src/modules/artefactPaths.stories.tsx` asserts every artefact type in
`frontend/src/modules/registeredArtefactTypes.json` resolves to a page, so a type
can never be linkable yet unreachable. That file must therefore equal the backend
registry; this test fails, naming the difference, when a module registers (or
drops) an artefact type without the file being updated. The frontend is not part
of the backend image, so the test is skipped there.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.modules.registry import get_all_registered_artefact_types

FIXTURE = Path(__file__).resolve().parents[2] / "frontend" / "src" / "modules" / "registeredArtefactTypes.json"


@pytest.mark.skipif(not FIXTURE.exists(), reason="frontend sources are not available (backend-only image)")
def test_frontend_route_fixture_matches_the_backend_artefact_type_registry():
    listed = set(json.loads(FIXTURE.read_text()))
    registered = get_all_registered_artefact_types()
    assert listed == registered, (
        f"frontend/src/modules/registeredArtefactTypes.json is out of date. Missing: {sorted(registered - listed)}; "
        f"stale: {sorted(listed - registered)}. Update the file, and give any new type a page via its module's "
        "`artefactPaths` (frontend/src/modules/<key>/module.ts) so it is reachable from a link."
    )


NOTIFICATION_KINDS_FIXTURE = (
    Path(__file__).resolve().parents[2] / "frontend" / "src" / "modules" / "notificationTargetKinds.json"
)


@pytest.mark.skipif(not NOTIFICATION_KINDS_FIXTURE.exists(), reason="frontend sources are not available (backend-only image)")
def test_frontend_notification_kind_fixture_matches_the_backend_vocabulary():
    """`notificationTargets.stories.tsx` asserts every kind in this file has a resolver and opens a mounted route, so the
    file must equal the backend's vocabulary (core's kinds plus each module's)."""
    from app.modules.registry import get_all_notification_target_kinds

    listed = set(json.loads(NOTIFICATION_KINDS_FIXTURE.read_text()))
    registered = set(get_all_notification_target_kinds())
    assert listed == registered, (
        f"frontend/src/modules/notificationTargetKinds.json is out of date. Missing: {sorted(registered - listed)}; "
        f"stale: {sorted(listed - registered)}. Update the file, give the kind a sample in notificationTargets.stories.tsx, "
        "and a resolver (core's in modules/notificationTargets.ts, a module's on `notificationTargets`)."
    )
