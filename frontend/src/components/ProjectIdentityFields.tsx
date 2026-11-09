/**
 * Module: components/ProjectIdentityFields
 *
 * The fields every new project starts with, whichever door it comes through: the organisation (when more than
 * one is available, alone on its row above a divider because the fields beneath depend on it), the name and the
 * summary. The New project and Import project dialogs both draw them, so a field added here reaches both. A
 * field only the create dialog takes goes in `beforeName` (the template, which precedes the name) or in
 * `children` (code, report name), between the name and the summary.
 */
import type { ReactNode } from "react";

import type { Organization } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { FormDivider, FormGridFull } from "./FormGrid";
import { TextAreaField, TextField } from "./FormFields";
import { LabeledSelect } from "./LabeledSelect";

/**
 * @param orgs The organisations the person can create a project in; the picker shows only when there are several.
 * @param orgLabelCap The deployment's capitalised organisation noun, used as the picker's label.
 * @param orgId The chosen organisation id.
 * @param onOrgChange Called with the newly chosen organisation id.
 * @param name The project name.
 * @param onNameChange Called with the edited name.
 * @param nameHelp Help text of the name field.
 * @param summary The project summary.
 * @param onSummaryChange Called with the edited summary.
 * @param beforeName Fields placed after the organisation and its divider and before the name. The first one
 *   that renders takes the initial focus when the organisation picker is absent, so it sets `autoFocus` itself.
 * @param children Fields placed between the name and the summary.
 */
export function ProjectIdentityFields({
  orgs, orgLabelCap, orgId, onOrgChange, name, onNameChange, nameHelp, summary, onSummaryChange, beforeName, children,
}: {
  orgs: Organization[];
  orgLabelCap: string;
  orgId: string;
  onOrgChange: (id: string) => void;
  name: string;
  onNameChange: (name: string) => void;
  nameHelp?: string;
  summary: string;
  onSummaryChange: (summary: string) => void;
  beforeName?: ReactNode;
  children?: ReactNode;
}) {
  const strings = useStrings();
  return (
    <>
      {orgs.length > 1 && (
        <>
          <FormGridFull>
            <LabeledSelect help={strings.help.newProjectOrganization} required
              label={orgLabelCap}
              value={orgId}
              onChange={onOrgChange}
              options={orgs.map((o) => ({ value: o.id, label: o.name }))}
              placeholder={null}
              inputProps={{ autoFocus: true }}
            />
          </FormGridFull>
          <FormDivider />
        </>
      )}
      {beforeName}
      <TextField required
        help={nameHelp}
        label={strings.projects.name}
        value={name}
        onChange={onNameChange}
        inputProps={{ autoFocus: orgs.length <= 1 && !beforeName }}
      />
      {children}
      <FormGridFull>
        <TextAreaField helpNotNeeded label={strings.projects.summary} value={summary} onChange={onSummaryChange} rows={2} />
      </FormGridFull>
    </>
  );
}
