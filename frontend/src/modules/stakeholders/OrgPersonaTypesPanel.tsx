/**
 * Module: modules/stakeholders/OrgPersonaTypesPanel
 *
 * The organisation tier of the Persona type vocabulary (Phase 0 resolution
 * 3) — a thin wrapper over the shared `OrgTypeVocabularyPanel`
 * (`components/TypeVocabularyPanels.tsx`). Registered on `orgAdminSections`
 * (Org Management): a type list is configuration an org admin manages, not
 * day-to-day persona content. Gated server-side on `persona_type_admin`.
 */
import { OrgTypeVocabularyPanel } from "../../components/TypeVocabularyPanels";
import { orgPersonaTypeApi } from "./api";
import type { PersonaTypeDefinition } from "./types";

export function OrgPersonaTypesPanel({ orgId }: { orgId: string }) {
  return (
    <OrgTypeVocabularyPanel<PersonaTypeDefinition>
      orgId={orgId}
      noun="Persona"
      api={orgPersonaTypeApi}
      inUseMessage="This type is still used by at least one project or persona. Disable it instead of deleting it."
      description={
        <>
          The shared Persona type vocabulary every project in this organisation sees by default (Primary, Secondary
          and Negative are seeded for a new organisation). A project may locally rename, disable, or add its own
          types without affecting this list or any other project.
        </>
      }
    />
  );
}
