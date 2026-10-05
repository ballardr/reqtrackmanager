/**
 * Module: modules/stakeholders/ProjectPersonaTypesPanel
 *
 * The project tier of the Persona type vocabulary — a thin wrapper over the
 * shared `ProjectTypeVocabularyPanel` (`components/TypeVocabularyPanels.tsx`),
 * registered on `projectAdminSections` (Project Admin). Gated server-side on
 * `persona_owner`.
 */
import { ProjectTypeVocabularyPanel } from "../../components/TypeVocabularyPanels";
import { projectPersonaApi } from "./api";

const api = {
  list: (projectId: string) => projectPersonaApi.listTypes(projectId),
  createLocal: (projectId: string, name: string, displayOrder?: number) =>
    projectPersonaApi.createLocalType(projectId, name, displayOrder),
  override: projectPersonaApi.overrideType,
  delete: projectPersonaApi.deleteType,
};

export function ProjectPersonaTypesPanel({ projectId }: { projectId: string }) {
  return (
    <ProjectTypeVocabularyPanel
      projectId={projectId}
      noun="Persona"
      api={api}
      description={
        <>
          This project's effective Persona type list — every active organisation type (with this project's own
          override, if any) plus any type added for this project only. Disabling a type here only affects this
          project.
        </>
      }
    />
  );
}
