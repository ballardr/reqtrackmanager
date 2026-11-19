/**
 * Module: components/ExternalSystemsPanels
 *
 * The administration of the external systems (Jira, ServiceNow, ...) a record's references can name, for the two tiers:
 * the organisation's list (`OrgExternalSystemsPanel`, every project sees it) and a project's view of it
 * (`ProjectExternalSystemsPanel`: rename, reorder, disable, add its own, hide an organisation default and add it back).
 * Thin wrappers over the shared `OrgTypeVocabularyPanel` and `ProjectTypeVocabularyPanel` with one extra text field per
 * row, the link template (an address with `{key}` in it, so a reference holding only a key opens its item).
 *
 * Gating is server-side (an organisation administrator for the organisation's list, project settings authority for a
 * project's), so both panels render their controls; a refusal surfaces through the list's own error handling. The text
 * that explains the list and the template is the help of the section the page puts these in (`strings.externalSystems`).
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
