/**
 * Module: components/ChangeRequestCreateModal
 *
 * The "New change request" dialog, shared by the Change requests page and the Links panel's "Create new"
 * (`CreateChangeRequestDialog`), so a field added to the form reaches both.
 *
 * Responsibilities:
 * - Load what the form needs (requirements, components, categories, target versions, custom fields, the organisation's
 *   members and shared resources).
 * - A request to modify a requirement is field-toggle driven: a field's proposed value is editable, and submitted as
 *   part of `changed_fields`, only once its checkbox is ticked, and it is pre-filled from the selected requirement's
 *   current version. A request for a new requirement has no requirement to compare with, so its form is a normal
 *   create form.
 * - Create the request, then apply its tags.
 *
 * Design decisions:
 * - Links are proposed with the request (`ProposedLinksEditor`) and created only if the approver merges them, so the
 *   form has no quick-link field: linking a draft request directly would bypass that approval.
 * - `defaultRequirementId` pre-selects the requirement to change (the deep link from a requirement's page, or the
 *   requirement whose Links panel opened the dialog); it is used only when that requirement can be changed (is locked).
 */
import { useEffect, useState } from "react";

import { DRAFT_ARTEFACT_ID, type CollectedLink } from "../api/artefactLinks";
import { api } from "../api/client";
import type {
  Category, ChangeableRequirementField, ChangeRequest, Component, CustomFieldDefinition, FileAsset, OrgUser, PrincipalRef,
  Project, ProjectStage, Requirement, RequirementLevel,
} from "../api/types";
import {
  CHANGEABLE_FIELD_LABEL, CHANGEABLE_REQUIREMENT_FIELDS, principalRef, REQUIREMENT_LEVEL_LABEL, savedPrincipalDisplay,
} from "../api/types";
import { useOrgLabel, useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useCommitTags } from "../hooks/useCommitTags";
import { useRecordCode } from "../hooks/useRecordCode";
import { useResetOnChange } from "../hooks/useResetOnChange";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { CustomFieldsForm } from "./CustomFieldsForm";
import { FormActions } from "./FormActions";
import { CheckboxField, TextAreaField, TextField } from "./FormFields";
import { FormGrid, FormGridFull } from "./FormGrid";
import { InlineSelect, LabeledSelect } from "./LabeledSelect";
import { Modal } from "./Modal";
import { PrincipalPicker } from "./PrincipalPicker";
import { ProposedLinksEditor } from "./ProposedLinksEditor";
import { TagField } from "./TagField";
import { labelOptions } from "../utils/labelOptions";

interface ProposedFields {
  name: string;
  reasoning: string;
  clarification: string;
  description: string;
  targetStageId: string;
  level: RequirementLevel;
  reviewDate: string;
  reviewLeadDays: string;
  reviewer: PrincipalRef | null;
}

const BLANK_PROPOSED: ProposedFields = {
  name: "", reasoning: "", clarification: "", description: "", targetStageId: "", level: "requirement",
  reviewDate: "", reviewLeadDays: "", reviewer: null,
};

/**
 * @param projectId The project the request is made in.
 * @param defaultRequirementId The requirement to pre-select for a request to modify it, when it can be changed.
 * @param onCreated Called with the new request's id once it exists and its tags are applied.
 * @param onClose Called when the dialog should close (dismissed, or after a successful create).
 */
export function ChangeRequestCreateModal({
  projectId, defaultRequirementId, onCreated, onClose,
}: {
  projectId: string;
  defaultRequirementId?: string;
  onCreated: (id: string) => void;
  onClose: () => void;
}) {
  const strings = useStrings();
  const recordCode = useRecordCode();
  const { showToast } = useToast();
  const commitTags = useCommitTags(projectId, "change_request");
  const orgLabel = useOrgLabel();
  const orgLabelCap = useOrgLabelCapitalized();

  const [loaded, setLoaded] = useState(false);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [organizationId, setOrganizationId] = useState<string | undefined>(undefined);
  const [orgResources, setOrgResources] = useState<FileAsset[]>([]);

  const [kind, setKind] = useState<"new_requirement" | "modify_requirement">("modify_requirement");
  const [requirementId, setRequirementId] = useState("");
  const [componentId, setComponentId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [changedFields, setChangedFields] = useState<Set<ChangeableRequirementField>>(new Set());
  const [proposed, setProposed] = useState<ProposedFields>(BLANK_PROPOSED);
  const [attachmentFileIds, setAttachmentFileIds] = useState<string[]>([]);
  // Links proposed with the request belong to one requirement (or to the one a new request creates), so a different
  // target starts over.
  const linksTarget = kind === "new_requirement" ? DRAFT_ARTEFACT_ID : requirementId;
  const [collectedLinks, setCollectedLinks] = useState<{ target: string; links: CollectedLink[] }>({ target: "", links: [] });
  const proposedLinks = collectedLinks.target === linksTarget ? collectedLinks.links : [];
  const setProposedLinks = (links: CollectedLink[]) => setCollectedLinks({ target: linksTarget, links });
  const [reason, setReason] = useState("");
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});
  const [tags, setTags] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      const [reqs, comps, cats, defs, stgs, proj] = await Promise.all([
        api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`),
        api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
        api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
        api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
        api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
        api.get<Project>(`/api/v1/projects/${projectId}`),
      ]);
      let users: OrgUser[] = [];
      let resources: FileAsset[] = [];
      try {
        [users, resources] = await Promise.all([
          api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`),
          api.get<FileAsset[]>(`/api/v1/orgs/${proj.organization_id}/resources`),
        ]);
      } catch {
        // No organisation role at all (rare): the reviewer and attachment pickers show fewer options.
      }
      if (!live) return;
      setRequirements(reqs);
      setComponents(comps);
      setCategories(cats);
      setCustomFieldDefs(defs);
      setStages(stgs);
      setOrganizationId(proj.organization_id);
      setOrgUsers(users);
      setOrgResources(resources);
      // A request to modify can only target a locked requirement (the server refuses an unlocked one): the requested
      // one when it qualifies, else the first locked one.
      const lockable = reqs.filter((r) => r.is_locked);
      const requested = lockable.find((r) => r.id === defaultRequirementId);
      setRequirementId(requested?.id ?? lockable[0]?.id ?? "");
      setComponentId(comps[0]?.id ?? "");
      setCategoryId(cats.find((c) => c.component_id === comps[0]?.id)?.id ?? "");
      setLoaded(true);
    })().catch((err) => { if (live) setError(toErrorMessage(err, strings.common.error)); });
    return () => { live = false; };
  }, [projectId, defaultRequirementId, strings.common.error]);

  const selectedRequirement = requirements.find((r) => r.id === requirementId) ?? null;
  // A modify request can only target an already-locked (approved or completed) requirement: offering an unlocked one
  // would only produce a refusal on submit.
  const lockableRequirements = requirements.filter((r) => r.is_locked);

  // Re-prime the proposed-value form from the newly-selected requirement's current version whenever the selection
  // changes, so a toggled field is always pre-filled with real content, and drop any previously toggled fields and
  // attachments, since they described a different requirement's content. Keyed on the resolved requirement's id too: the
  // requirement can be set before the list has loaded, and the form must be primed once it arrives.
  useResetOnChange([requirementId, kind, selectedRequirement?.id], () => {
    if (kind !== "modify_requirement" || !selectedRequirement) return;
    setProposed({
      name: selectedRequirement.name,
      reasoning: selectedRequirement.reasoning,
      clarification: selectedRequirement.clarification,
      description: selectedRequirement.description,
      targetStageId: selectedRequirement.target_stage_id,
      level: selectedRequirement.level,
      reviewDate: selectedRequirement.review_date ?? "",
      reviewLeadDays: selectedRequirement.review_lead_days != null ? String(selectedRequirement.review_lead_days) : "",
      reviewer: principalRef(selectedRequirement.reviewer),
    });
    setCustomFieldValues(selectedRequirement.custom_fields);
    setChangedFields(new Set());
    setAttachmentFileIds([]);
  });

  /** The collected links as the API takes them (the display fields are dropped). */
  function proposedLinksPayload() {
    return proposedLinks.map(({ link_type_id, direction, other_type, other_id, other_project_id }) => ({
      link_type_id, direction, other_type, other_id, other_project_id,
    }));
  }

  function toggleChangedField(field: ChangeableRequirementField) {
    setChangedFields((current) => {
      const next = new Set(current);
      if (next.has(field)) next.delete(field);
      else next.add(field);
      return next;
    });
  }

  function toggleAttachment(fileId: string) {
    setAttachmentFileIds((ids) => (ids.includes(fileId) ? ids.filter((i) => i !== fileId) : [...ids, fileId]));
  }

  async function createCr() {
    setError(null);
    try {
      let created: ChangeRequest;
      if (kind === "modify_requirement") {
        created = await api.post<ChangeRequest>(`/api/v1/projects/${projectId}/change-requests`, {
          kind,
          requirement_id: requirementId,
          changed_fields: Array.from(changedFields),
          proposed_name: changedFields.has("name") ? proposed.name : null,
          proposed_reasoning: changedFields.has("reasoning") ? proposed.reasoning : null,
          proposed_clarification: changedFields.has("clarification") ? proposed.clarification : null,
          proposed_description: changedFields.has("description") ? proposed.description : null,
          proposed_target_stage_id: changedFields.has("target_stage_id") ? proposed.targetStageId : null,
          proposed_level: changedFields.has("level") ? proposed.level : null,
          proposed_review_date: changedFields.has("review_date") ? proposed.reviewDate || null : null,
          proposed_review_lead_days:
            changedFields.has("review_lead_days") && proposed.reviewLeadDays ? Number(proposed.reviewLeadDays) : null,
          proposed_reviewer: changedFields.has("reviewer_id") ? proposed.reviewer : null,
          proposed_attachment_file_ids: changedFields.has("attachments") ? attachmentFileIds : [],
          custom_fields: changedFields.has("custom_fields") ? customFieldValues : {},
          proposed_links: proposedLinksPayload(),
          reason,
        });
      } else {
        created = await api.post<ChangeRequest>(`/api/v1/projects/${projectId}/change-requests`, {
          kind,
          proposed_name: proposed.name,
          proposed_reasoning: proposed.reasoning,
          proposed_clarification: proposed.clarification,
          proposed_description: proposed.description,
          proposed_component_id: componentId,
          proposed_category_id: categoryId,
          proposed_target_stage_id: proposed.targetStageId || null,
          proposed_level: proposed.level,
          proposed_review_date: proposed.reviewDate || null,
          proposed_review_lead_days: proposed.reviewLeadDays ? Number(proposed.reviewLeadDays) : null,
          proposed_reviewer: proposed.reviewer,
          reason,
          custom_fields: customFieldValues,
          proposed_links: proposedLinksPayload(),
        });
      }
      showToast(strings.changeRequests.created);
      await commitTags(created.id, tags);
      onCreated(created.id);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  function renderFieldEditor(field: ChangeableRequirementField) {
    switch (field) {
      case "name":
        return (
          <input
            className="input"
            value={proposed.name}
            onChange={(e) => setProposed((p) => ({ ...p, name: e.target.value }))}
          />
        );
      case "reasoning":
        return (
          <AutoGrowTextarea
            rows={2}
            value={proposed.reasoning}
            onChange={(value) => setProposed((p) => ({ ...p, reasoning: value }))}
          />
        );
      case "clarification":
        return (
          <AutoGrowTextarea
            rows={2}
            value={proposed.clarification}
            onChange={(value) => setProposed((p) => ({ ...p, clarification: value }))}
          />
        );
      case "description":
        return (
          <AutoGrowTextarea
            rows={2}
            value={proposed.description}
            onChange={(value) => setProposed((p) => ({ ...p, description: value }))}
          />
        );
      case "target_stage_id":
        return (
          <InlineSelect
            ariaLabel={CHANGEABLE_FIELD_LABEL.target_stage_id}
            value={proposed.targetStageId}
            placeholder={null}
            onChange={(targetStageId) => setProposed((p) => ({ ...p, targetStageId }))}
            options={stages.map((s) => ({ value: s.id, label: s.name }))}
          />
        );
      case "level":
        return (
          <InlineSelect<RequirementLevel>
            ariaLabel={CHANGEABLE_FIELD_LABEL.level}
            value={proposed.level}
            placeholder={null}
            onChange={(level) => setProposed((p) => ({ ...p, level }))}
            options={labelOptions(REQUIREMENT_LEVEL_LABEL)}
          />
        );
      case "review_date":
        return (
          <input
            className="input"
            type="date"
            value={proposed.reviewDate}
            onChange={(e) => setProposed((p) => ({ ...p, reviewDate: e.target.value }))}
          />
        );
      case "review_lead_days":
        return (
          <input
            className="input"
            type="number"
            min={0}
            value={proposed.reviewLeadDays}
            onChange={(e) => setProposed((p) => ({ ...p, reviewLeadDays: e.target.value }))}
          />
        );
      case "reviewer_id":
        return (
          <PrincipalPicker
            orgUsers={orgUsers} organizationId={organizationId} projectId={projectId}
            value={proposed.reviewer} display={savedPrincipalDisplay(proposed.reviewer, selectedRequirement?.reviewer)}
            onChange={(reviewer) => setProposed((p) => ({ ...p, reviewer }))}
            ariaLabel={strings.requirements.reviewer} placeholder={strings.reviews.unassigned}
          />
        );
      case "custom_fields":
        return (
          <CustomFieldsForm
            definitions={customFieldDefs}
            values={customFieldValues}
            onChange={(fieldId, value) => setCustomFieldValues((v) => ({ ...v, [fieldId]: value }))}
          />
        );
      case "attachments":
        return (
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            {orgResources.length === 0 && (
              <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                {strings.changeRequests.noAttachmentsAvailable(orgLabel, orgLabelCap)}
              </p>
            )}
            {orgResources.map((r) => (
              <CheckboxField helpNotNeeded key={r.id} label={r.filename} checked={attachmentFileIds.includes(r.id)} onChange={() => toggleAttachment(r.id)} />
            ))}
          </div>
        );
      default:
        return null;
    }
  }


  if (!loaded) return null;
  return (
    <Modal title={strings.changeRequests.newChangeRequest} onClose={onClose} size="lg">
    <div className="stack">
      <div className="row">
        <label>
          <input
            type="radio"
            checked={kind === "modify_requirement"}
            onChange={() => setKind("modify_requirement")}
          />{" "}
          {strings.changeRequests.kindModify}
        </label>
        <label>
          <input type="radio" checked={kind === "new_requirement"} onChange={() => setKind("new_requirement")} />{" "}
          {strings.changeRequests.kindNew}
        </label>
      </div>

      {kind === "modify_requirement" ? (
        <>
          <LabeledSelect helpNotNeeded required
            label={strings.changeRequests.selectARequirement}
            value={requirementId}
            onChange={setRequirementId}
            options={lockableRequirements.map((r) => ({ value: r.id, label: `${recordCode.code(r.unique_code)} — ${r.name}` }))}
            placeholder={null}
          />
          {lockableRequirements.length === 0 && (
            <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              {strings.changeRequests.noLockableRequirements}
            </p>
          )}
          <div className="stack">
            <strong>{strings.changeRequests.fieldsToChange}</strong>
            <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
              {strings.changeRequests.fieldsToChangeHint}
            </p>
            {CHANGEABLE_REQUIREMENT_FIELDS.map((field) => (
              <div key={field} className="stack" style={{ gap: "var(--space-2)" }}>
                <label className="checkbox-label" style={{ gap: "var(--space-3)" }}>
                  <input type="checkbox" checked={changedFields.has(field)} onChange={() => toggleChangedField(field)} />
                  {CHANGEABLE_FIELD_LABEL[field]}
                </label>
                {changedFields.has(field) && <div style={{ marginLeft: "var(--space-6)" }}>{renderFieldEditor(field)}</div>}
              </div>
            ))}
          </div>
        </>
      ) : (
        <FormGrid minColumn="18rem">
          <LabeledSelect help={strings.help.proposedRequirementComponent} required
            label={strings.requirements.component}
            value={componentId}
            onChange={(nextComponentId) => {
              setComponentId(nextComponentId);
              setCategoryId(categories.find((c) => c.component_id === nextComponentId)?.id ?? "");
            }}
            options={components.map((c) => ({ value: c.id, label: c.name }))}
            placeholder={null}
          />
          <LabeledSelect help={strings.help.proposedRequirementCategory} required
            label={strings.requirements.category}
            value={categoryId}
            onChange={setCategoryId}
            options={categories.filter((c) => c.component_id === componentId).map((c) => ({ value: c.id, label: c.name }))}
            placeholder={null}
          />
          <FormGridFull>
            <TextField help={strings.help.proposedRequirementName} required
              label={strings.changeRequests.proposedName}
              value={proposed.name}
              onChange={(next) => setProposed((p) => ({ ...p, name: next }))}
            />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField help={strings.help.proposedRequirementReasoning}
              label={strings.changeRequests.proposedReasoning}
              value={proposed.reasoning}
              onChange={(next) => setProposed((p) => ({ ...p, reasoning: next }))}
            />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField help={strings.help.requirementClarification}
              label={strings.requirements.clarification}
              value={proposed.clarification}
              onChange={(next) => setProposed((p) => ({ ...p, clarification: next }))}
            />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField helpNotNeeded
              label={strings.requirements.description}
              value={proposed.description}
              onChange={(next) => setProposed((p) => ({ ...p, description: next }))}
            />
          </FormGridFull>
          <LabeledSelect help={strings.help.requirementTargetVersion}
            label={strings.requirements.targetVersion}
            value={proposed.targetStageId}
            onChange={(next) => setProposed((p) => ({ ...p, targetStageId: next }))}
            options={stages.map((s) => ({ value: s.id, label: s.name }))}
            placeholder="—"
          />
          <LabeledSelect help={strings.help.requirementLevel}
            label={strings.requirements.level}
            value={proposed.level}
            onChange={(next) => setProposed((p) => ({ ...p, level: next as RequirementLevel }))}
            options={[
              { value: "requirement", label: REQUIREMENT_LEVEL_LABEL.requirement },
              { value: "recommended", label: REQUIREMENT_LEVEL_LABEL.recommended },
              { value: "optional", label: REQUIREMENT_LEVEL_LABEL.optional },
            ]}
            placeholder={null}
          />
          <FormGridFull>
            <CustomFieldsForm
              definitions={customFieldDefs}
              values={customFieldValues}
              onChange={(fieldId, value) => setCustomFieldValues((v) => ({ ...v, [fieldId]: value }))}
            />
          </FormGridFull>
        </FormGrid>
      )}

      {linksTarget && (
        <ProposedLinksEditor
          projectId={projectId}
          artefactId={linksTarget}
          links={proposedLinks}
          onChange={setProposedLinks}
        />
      )}

      <TextAreaField helpNotNeeded required label={strings.changeRequests.reason} value={reason} onChange={setReason} />
      <FormActions
        error={error} onCancel={onClose} onSave={createCr} saveLabel={strings.common.create}
        saveDisabled={
          !reason ||
          (kind === "modify_requirement"
            ? !requirementId || changedFields.size === 0
            : !proposed.name || !componentId || !categoryId)
        }
      />
      {kind === "modify_requirement" && changedFields.size === 0 && (
        <span className="text-muted" style={{ fontSize: "0.85rem" }}>
          {strings.changeRequests.selectAtLeastOneField}
        </span>
      )}
      <TagField projectId={projectId} artefactType="change_request" value={tags} onChange={setTags} />
    </div>
    </Modal>
  );
}
