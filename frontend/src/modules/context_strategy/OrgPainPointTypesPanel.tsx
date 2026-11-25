/**
 * Module: modules/context_strategy/OrgPainPointTypesPanel
 *
 * The organisation-scoped base tier of Pain Point's type vocabulary: a thin wrapper over the shared
 * `OrgTypeVocabularyPanel` (`components/TypeVocabularyPanels.tsx`, which documents the shared behaviour).
 *
 * Placement is `orgAdminSections` (Org Management), not `orgResourceSections`: a type vocabulary is a configuration
 * table an organisation administrator manages, as in `DecisionTemplatesPanel.tsx`. Gated on the
 * `pain_point_type_admin` module role, enforced server-side.
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
      withDefinition
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
