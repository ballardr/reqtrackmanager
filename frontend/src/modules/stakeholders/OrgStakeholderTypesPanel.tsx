/**
 * Module: modules/stakeholders/OrgStakeholderTypesPanel
 *
 * The organisation tier of the Stakeholder type vocabulary (Phase 0 resolution
 * 3) — a thin wrapper over the shared `OrgTypeVocabularyPanel`
 * (`components/TypeVocabularyPanels.tsx`). Registered on `orgAdminSections`
 * (Org Management). Gated server-side on `stakeholder_type_admin`.
 */
import { OrgTypeVocabularyPanel } from "../../components/TypeVocabularyPanels";
import { orgStakeholderTypeApi } from "./api";
import type { PersonaTypeDefinition } from "./types";

export function OrgStakeholderTypesPanel({ orgId }: { orgId: string }) {
  return (
    <OrgTypeVocabularyPanel<PersonaTypeDefinition>
      orgId={orgId}
      noun="Stakeholder"
      api={orgStakeholderTypeApi}
      inUseMessage="This type is still used by at least one project or stakeholder. Disable it instead of deleting it."
      description={
        <>
          The shared Stakeholder type vocabulary every project in this organisation sees by default (Customer, End
          user, Regulator and the rest are seeded for a new organisation). A project may locally rename, disable, or
          add its own types without affecting this list or any other project.
        </>
      }
    />
  );
}
