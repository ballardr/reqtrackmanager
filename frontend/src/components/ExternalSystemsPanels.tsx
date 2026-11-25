/**
 * Module: components/ExternalSystemsPanels
 *
 * Administration of the external systems (Jira, ServiceNow ...) a record's references can name, for two tiers: the
 * organisation's list (`OrgExternalSystemsPanel`, visible to every project) and a project's view of it
 * (`ProjectExternalSystemsPanel`: rename, reorder, disable, add its own, hide an organisation default and restore
 * it). Thin wrappers over `OrgTypeVocabularyPanel` and `ProjectTypeVocabularyPanel` with one extra text field per
 * row, the link template (an address containing `{key}`).
 *
 * Gating is server-side, so both panels render their controls and a refusal surfaces through the list's error
 * handling. The explanatory text is the help of the section the page puts them in (`strings.externalSystems`).
 *
 * Dependencies: `api/externalSystems`, `components/TypeVocabularyPanels`.
 */
import { externalSystemApi } from "../api/externalSystems";
import { t } from "../i18n/strings";
import { OrgTypeVocabularyPanel, ProjectTypeVocabularyPanel, type VocabularyTextField } from "./TypeVocabularyPanels";

const strings = t();

/** The link template column both tiers carry. */
const LINK_TEMPLATE_FIELD: VocabularyTextField = {
  key: "url_template",
  label: strings.externalSystems.linkTemplate,
  placeholder: strings.externalSystems.linkTemplatePlaceholder,
  ariaLabel: strings.externalSystems.linkTemplateAria,
};

/** @param orgId The organisation whose list to administer. */
export function OrgExternalSystemsPanel({ orgId }: { orgId: string }) {
  return (
    <OrgTypeVocabularyPanel
      orgId={orgId} noun={strings.externalSystems.noun} api={externalSystemApi.org}
      textField={LINK_TEMPLATE_FIELD} inUseMessage={strings.externalSystems.inUse}
    />
  );
}

/** @param projectId The project whose view of the list to administer. */
export function ProjectExternalSystemsPanel({ projectId }: { projectId: string }) {
  return <ProjectTypeVocabularyPanel projectId={projectId} noun={strings.externalSystems.noun} api={externalSystemApi.project} textField={LINK_TEMPLATE_FIELD} />;
}
