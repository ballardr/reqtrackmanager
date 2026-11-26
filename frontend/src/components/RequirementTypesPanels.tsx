/**
 * Module: components/RequirementTypesPanels
 *
 * Administration of the requirement types (Business, Stakeholder and Project Requirement by default) at two tiers:
 * the organisation's list (`OrgRequirementTypesPanel`, offered to every project) and a project's view of it
 * (`ProjectRequirementTypesPanel`: rename, reorder, disable, add its own, hide an organisation default and restore it).
 * Thin wrappers over `OrgTypeVocabularyPanel` and `ProjectTypeVocabularyPanel`; a type has a name, a place in the list and a rank (priority).
 *
 * Gating is server-side, so both panels render their controls and a refusal surfaces through the list's error
 * handling. The explanatory text is the help of the section the page puts them in (`strings.requirementTypes`).
 *
 * Dependencies: `api/requirementTypes`, `components/TypeVocabularyPanels`.
 */
import { requirementTypeApi } from "../api/requirementTypes";
import { useStrings } from "../context/TerminologyContext";
import { OrgTypeVocabularyPanel, ProjectTypeVocabularyPanel, type VocabularyTextField } from "./TypeVocabularyPanels";

/** The rank column both tiers carry: a short whole number, blank for unranked (a project's blank follows the organisation). */
function rankField(strings: ReturnType<typeof useStrings>): VocabularyTextField {
  return {
    key: "rank", label: strings.requirementTypes.rank, placeholder: strings.requirementTypes.rankPlaceholder,
    ariaLabel: strings.requirementTypes.rank, track: "7rem", inputType: "number", help: strings.help.requirementTypeRank,
  };
}

/** @param orgId The organisation whose list to administer. */
export function OrgRequirementTypesPanel({ orgId }: { orgId: string }) {
  const strings = useStrings();
  return (
    <OrgTypeVocabularyPanel
      orgId={orgId} noun={strings.requirementTypes.noun} api={requirementTypeApi.org} inUseMessage={strings.requirementTypes.inUse}
      textField={rankField(strings)}
    />
  );
}

/** @param projectId The project whose view of the list to administer. */
export function ProjectRequirementTypesPanel({ projectId }: { projectId: string }) {
  const strings = useStrings();
  return <ProjectTypeVocabularyPanel projectId={projectId} noun={strings.requirementTypes.noun} api={requirementTypeApi.project} textField={rankField(strings)} />;
}
