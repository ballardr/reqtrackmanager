"""The module contributes one navigation entry, the System Architecture page, which is offered while any of the
Elements, Connections or Diagrams sub-components is on."""

from __future__ import annotations

from app.modules.architecture.module import MODULE_DEFINITION
from app.modules.architecture.service import (
    CONNECTION_SUBCOMPONENT_KEY,
    DIAGRAM_SUBCOMPONENT_KEY,
    ELEMENT_SUBCOMPONENT_KEY,
)


def test_one_navigation_entry_serves_the_three_lists() -> None:
    manifest = MODULE_DEFINITION.frontend_manifest
    assert manifest is not None
    assert manifest.nav_label == "System Architecture"
    assert manifest.nav_path == "/projects/{project_id}/modules/architecture"
    assert manifest.additional_nav_entries == ()
    assert set(manifest.nav_sub_components_any) == {
        ELEMENT_SUBCOMPONENT_KEY, CONNECTION_SUBCOMPONENT_KEY, DIAGRAM_SUBCOMPONENT_KEY,
    }


def test_the_entry_is_offered_while_any_list_is_on_and_hidden_when_all_are_off() -> None:
    manifest = MODULE_DEFINITION.frontend_manifest
    assert manifest is not None
    entries = manifest.all_nav_entries()
    assert len(entries) == 1
    assert entries[0].sub_components_any == (ELEMENT_SUBCOMPONENT_KEY, CONNECTION_SUBCOMPONENT_KEY, DIAGRAM_SUBCOMPONENT_KEY)
