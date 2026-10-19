/**
 * Module: components/RequirementFields
 *
 * The field group shared by the requirement create dialog (`RequirementsPage`) and the requirement
 * edit form (`RequirementDetailPage`), so a field added to a requirement appears in both. It holds
 * every field that is the same in the two: name, reasoning, clarification, description, target
 * version, level, review date, reminder lead time, reviewer and owner.
 *
 * Fields that differ stay with the page: the create dialog puts component and category (chosen
 * once, at creation) between description and target version through `afterDescription`; custom
 * fields, tags, links and the edit form's change note follow the group.
 *
 * The component is controlled and framework-free: the page owns the values, so the edit form can
 * keep its dirty-tracking around `onChange`.
 */
import type { ReactNode } from "react";

import type { OrgUser, Principal, ProjectStage, RequirementLevel } from "../api/types";
import { REQUIREMENT_LEVEL_LABEL, savedPrincipalDisplay } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { DateField, TextAreaField, TextField } from "./FormFields";
import { FormGridFull } from "./FormGrid";
import { LabeledSelect } from "./LabeledSelect";
import { PrincipalFormField } from "./PrincipalFormField";
import type { RequirementFieldValues } from "./requirementFieldValues";

const LEVELS: RequirementLevel[] = ["requirement", "recommended", "optional"];

/**
 * @param values Current field values.
 * @param onChange Called with the whole next value set after any field changes.
 * @param stages The project's target versions.
 * @param orgUsers Organisation members, for the owner and reviewer pickers.
 * @param organizationId The project's organisation (enables server-side user and group search).
 * @param projectId The project (enables project groups).
 * @param saved The record's own resolved owner and reviewer, when editing; labels a group the
 *   viewer cannot list.
 * @param ownerPlaceholder Hint for an empty owner (create: "defaults to you").
 * @param afterDescription Page-specific fields placed between description and target version.
 */
export function RequirementFields({
  values, onChange, stages, orgUsers, organizationId, projectId, saved, ownerPlaceholder, afterDescription,
}: {
  values: RequirementFieldValues;
  onChange: (next: RequirementFieldValues) => void;
  stages: ProjectStage[];
  orgUsers: OrgUser[];
  organizationId?: string;
  projectId?: string;
  saved?: { owner: Principal | null; reviewer: Principal | null };
  ownerPlaceholder?: string;
  afterDescription?: ReactNode;
}) {
  const strings = useStrings();
  const set = <K extends keyof RequirementFieldValues>(key: K, value: RequirementFieldValues[K]) =>
    onChange({ ...values, [key]: value });
  return (
    <>
      <FormGridFull>
        <TextField label={strings.requirements.name} value={values.name} onChange={(next) => set("name", next)} placeholder={strings.requirements.name} />
      </FormGridFull>
      <FormGridFull>
        <TextAreaField autoGrow label={strings.requirements.reasoning} rows={3} value={values.reasoning} onChange={(next) => set("reasoning", next)} inputProps={{ placeholder: strings.requirements.reasoning }} />
      </FormGridFull>
      <FormGridFull>
        <TextAreaField autoGrow label={strings.requirements.clarification} rows={2} value={values.clarification} onChange={(next) => set("clarification", next)} inputProps={{ placeholder: strings.requirements.clarification }} />
      </FormGridFull>
      <FormGridFull>
        <TextAreaField autoGrow label={strings.requirements.description} rows={2} value={values.description} onChange={(next) => set("description", next)} inputProps={{ placeholder: strings.requirements.description }} />
      </FormGridFull>
      {afterDescription}
      <LabeledSelect
        label={strings.requirements.targetVersion}
        value={values.targetStageId}
        onChange={(next) => set("targetStageId", next)}
        options={stages.map((s) => ({ value: s.id, label: s.name }))}
        placeholder={null}
      />
      <LabeledSelect
        label={strings.requirements.level}
        value={values.level}
        onChange={(next) => set("level", next as RequirementLevel)}
        options={LEVELS.map((value) => ({ value, label: REQUIREMENT_LEVEL_LABEL[value] }))}
        placeholder={null}
      />
      <DateField label={strings.requirements.reviewDate} value={values.reviewDate} onChange={(next) => set("reviewDate", next)} />
      <TextField
        label={strings.requirements.reviewLeadDays} value={values.reviewLeadDays}
        onChange={(next) => set("reviewLeadDays", next)} inputProps={{ type: "number", min: 0 }}
      />
      <PrincipalFormField
        label={strings.requirements.reviewer} orgUsers={orgUsers} organizationId={organizationId}
        projectId={projectId} value={values.reviewer}
        display={saved ? savedPrincipalDisplay(values.reviewer, saved.reviewer) : undefined}
        onChange={(reviewer) => set("reviewer", reviewer)}
        ariaLabel={strings.requirements.reviewer} placeholder={strings.reviews.unassigned}
      />
      <PrincipalFormField
        label={strings.requirements.owner} orgUsers={orgUsers} organizationId={organizationId}
        projectId={projectId} value={values.owner}
        display={saved ? savedPrincipalDisplay(values.owner, saved.owner) : undefined}
        onChange={(owner) => set("owner", owner)}
        ariaLabel={strings.requirements.owner} placeholder={ownerPlaceholder ?? strings.reviews.unassigned} clearLabel="Clear"
      />
    </>
  );
}
