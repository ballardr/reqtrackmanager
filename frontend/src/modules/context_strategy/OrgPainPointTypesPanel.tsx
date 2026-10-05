/**
 * Module: modules/context_strategy/OrgPainPointTypesPanel
 *
 * The organisation-scoped shared base tier of Pain Point's type vocabulary
 * (Phase 0 Q3, source overview §6.2) — a thin wrapper over the shared
 * `OrgTypeVocabularyPanel` (`components/TypeVocabularyPanels.tsx`, which
 * documents the shared behaviour: `DefinitionList` rename/reorder/add/
 * delete, the active toggle, and why a 409 on delete blocks rather than
 * offering reassignment).
 *
 * **Placement: `orgAdminSections` (Org Management), not `orgOverviewSections`
 * (Org Dashboard)** — a type vocabulary is a configuration table an org
 * admin manages, not day-to-day artefact content like an org-scoped
 * Strategy, the same distinction `DecisionTemplatesPanel.tsx` draws
 * (Decided by: Agent). Gated on the `pain_point_type_admin` module role,
 * enforced server-side.
 */
import { OrgTypeVocabularyPanel } from "../../components/TypeVocabularyPanels";
import { orgPainPointTypeApi } from "./api";
import type { PainPointTypeDefinition } from "./types";

export function OrgPainPointTypesPanel({ orgId }: { orgId: string }) {
  return (
    <OrgTypeVocabularyPanel<PainPointTypeDefinition>
      orgId={orgId}
      noun="Pain Point"
      api={orgPainPointTypeApi}
      description={
        <>
          The shared Pain Point type vocabulary every project in this organisation sees by default (Market, User, and
          Operator are seeded automatically for a new organisation — §6.2). A project may locally rename, disable, or
          add its own types without affecting this list or any other project.
        </>
      }
    />
  );
}
