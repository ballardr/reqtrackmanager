import { Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  ChangeableRequirementField,
  ChangeRequest,
  ChangeRequestStatus,
  Component,
  Category,
  CustomFieldDefinition,
  FileAsset,
  OrgUser,
  Project,
  ProjectStage,
  Requirement,
  RequirementLevel,
} from "../api/types";
import {
  CHANGE_REQUEST_STATUS_LABEL,
  CHANGEABLE_FIELD_LABEL,
  CHANGEABLE_REQUIREMENT_FIELDS,
  REQUIREMENT_LEVEL_LABEL,
} from "../api/types";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { FilterBadge } from "../components/FilterBadge";
import { FilterField, FilterPanel } from "../components/FilterPanel";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Modal } from "../components/Modal";
import { cycleSort, SortableHeader, type SortState } from "../components/SortableHeader";
import { Spinner } from "../components/Spinner";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { useOrgLabel, useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings, useTerm } from "../context/TerminologyContext";
import { useToast } from "../context/ToastContext";

const PAGE_SIZE = 30;

const CR_STATUS_OPTIONS: ChangeRequestStatus[] = [
  "draft", "submitted", "in_review", "approved", "rejected", "withdrawn",
];

// Tri-state status filter (2026-08 UX audit roadmap, "Default Change
// Requests to an active-only status filter") — a change request list is
// usually consulted for what still needs a decision, not a permanent
// archive of every decision ever made, so the default view narrows to the
// three non-terminal statuses (draft/submitted/in_review, matching the
// backend's own `active_only` filter in
// `backend/app/routers/change_requests.py::list_change_requests`).
// "active" (default) sends `active_only=true` and no `cr_status`; "" ("All
// statuses") sends neither param; a specific `ChangeRequestStatus` sends
// `cr_status` as before. A sentinel string distinct from both "" and any
// real status value is needed so the three states are distinguishable in
// the `<select>` and in `listParams()` below.
type CrStatusFilterValue = ChangeRequestStatus | "" | "active";

interface ProposedFields {
  name: string;
  reasoning: string;
  clarification: string;
  description: string;
  targetStageId: string;
  level: RequirementLevel;
  reviewDate: string;
  reviewLeadDays: string;
  reviewerId: string;
}

const BLANK_PROPOSED: ProposedFields = {
  name: "",
  reasoning: "",
  clarification: "",
  description: "",
  targetStageId: "",
  level: "requirement",
  reviewDate: "",
  reviewLeadDays: "",
  reviewerId: "",
};

/** Change request list and creation form (introduction, C-G-03), with
 * incremental "load more" pagination (U-P-06) for large CR sets.
 *
 * For a MODIFY_REQUIREMENT change request, the form is field-toggle driven:
 * a field's proposed value is only editable (and only submitted as part of
 * `changed_fields`) once its checkbox is ticked, and it's pre-filled from
 * the selected requirement's current version the moment it's toggled on or
 * the selected requirement changes — the user never has to copy values
 * across by hand. NEW_REQUIREMENT change requests have no existing
 * requirement to diff against, so every field is always "changed" and the
 * form looks like a normal create form.
 */
export function ChangeRequestsPage() {
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const { showToast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [crs, setCrs] = useState<ChangeRequest[] | null>(null);
  const [total, setTotal] = useState(0);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [orgResources, setOrgResources] = useState<FileAsset[]>([]);
  const orgLabel = useOrgLabel();
  const orgLabelCap = useOrgLabelCapitalized();
  const [showForm, setShowForm] = useState(false);
  const [kind, setKind] = useState<"new_requirement" | "modify_requirement">("modify_requirement");
  const [requirementId, setRequirementId] = useState("");
  const [componentId, setComponentId] = useState("");
  const [categoryId, setCategoryId] = useState("");
  const [changedFields, setChangedFields] = useState<Set<ChangeableRequirementField>>(new Set());
  const [proposed, setProposed] = useState<ProposedFields>(BLANK_PROPOSED);
  const [attachmentFileIds, setAttachmentFileIds] = useState<string[]>([]);
  const [reason, setReason] = useState("");
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});
  const changeRequestTerm = useTerm("change_request");
  const [viewMode, setViewMode] = useViewMode("change-requests");
  const [statusFilter, setStatusFilter] = useState<CrStatusFilterValue>("active");
  const [targetStageFilter, setTargetStageFilter] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  // Column-header sorting (2026-08 UX audit roadmap) — backend `sort`/
  // `order` param, same reasoning as `RequirementsPage.tsx`: this list is
  // already backend-paginated (`PAGE_SIZE`/`LoadMoreButton`), so a
  // client-side sort would only reorder the currently-loaded page.
  type ChangeRequestSortKey = "proposed_name" | "status" | "created_at";
  const [sort, setSort] = useState<SortState<ChangeRequestSortKey> | null>(null);

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (statusFilter === "active") params.set("active_only", "true");
    else if (statusFilter) params.set("cr_status", statusFilter);
    if (targetStageFilter) params.set("target_stage_id", targetStageFilter);
    if (sort) {
      params.set("sort", sort.key);
      params.set("order", sort.direction);
    }
    return params;
  }

  async function loadChangeRequests(offset: number, append: boolean) {
    if (!projectId) return;
    const page = await api.getPage<ChangeRequest>(
      `/api/v1/projects/${projectId}/change-requests?${listParams(offset).toString()}`
    );
    setCrs((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
  }

  async function reload() {
    if (!projectId) return;
    // Captured synchronously, before the `await` below yields control —
    // `searchParams` is a mutable URLSearchParams instance, and the
    // deep-link effect's `setSearchParams` updater mutates it in place
    // (not a copy), so reading `searchParams.get(...)` *after* the await
    // would see it already stripped by that effect, which runs
    // synchronously in between.
    const deepLinkRequirementId = searchParams.get("requirement");
    const [reqs, comps, cats, defs, stgs, proj] = await Promise.all([
      api.get<Requirement[]>(`/api/v1/projects/${projectId}/requirements`),
      api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
      api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<Project>(`/api/v1/projects/${projectId}`),
      loadChangeRequests(0, false),
    ]);
    setRequirements(reqs);
    setComponents(comps);
    setCategories(cats);
    setCustomFieldDefs(defs);
    setStages(stgs);
    // Skip defaulting to the first requirement when a specific one was
    // requested via the "Make change request" deep link (?requirement=) —
    // uses the value captured above, not a fresh read, for the reason
    // explained there. Defaults to the first *locked* one — the backend now
    // rejects a modify-CR against a still-draft/reviewed requirement (2026-08
    // UX audit roadmap, "No requirement approval action; change requests can
    // target draft requirements"), so defaulting to an unlocked one would
    // just fail on submit.
    const firstLockedRequirement = reqs.find((r) => r.is_locked);
    if (!requirementId && !deepLinkRequirementId && firstLockedRequirement) setRequirementId(firstLockedRequirement.id);
    const selectedComponentId = componentId || comps[0]?.id || "";
    if (!componentId && comps[0]) setComponentId(comps[0].id);
    if (!categoryId) {
      const firstOwnCategory = cats.find((c) => c.component_id === selectedComponentId);
      if (firstOwnCategory) setCategoryId(firstOwnCategory.id);
    }
    try {
      const [users, resources] = await Promise.all([
        api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`),
        api.get<FileAsset[]>(`/api/v1/orgs/${proj.organization_id}/resources`),
      ]);
      setOrgUsers(users);
      setOrgResources(resources);
    } catch {
      // No org role at all (rare) — reviewer/attachment pickers just show
      // fewer options rather than breaking the page.
    }
  }

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, statusFilter, targetStageFilter, sort]);

  // Deep-linked from a requirement's "Make change request" button
  // (?requirement=<id>) — pre-selects that requirement for a
  // MODIFY_REQUIREMENT change request and opens the form.
  useEffect(() => {
    const deepLinkedRequirementId = searchParams.get("requirement");
    if (deepLinkedRequirementId) {
      setKind("modify_requirement");
      setRequirementId(deepLinkedRequirementId);
      setShowForm(true);
      setSearchParams((params) => {
        params.delete("requirement");
        return params;
      }, { replace: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const selectedRequirement = requirements.find((r) => r.id === requirementId) ?? null;
  // A modify-CR can only target an already-locked (approved/completed)
  // requirement (2026-08 UX audit roadmap, same reasoning as the default-
  // selection comment above) — offering an unlocked one in this dropdown
  // would just produce a 400 on submit.
  const lockableRequirements = requirements.filter((r) => r.is_locked);

  // Re-prime the proposed-value form from the newly-selected requirement's
  // current version whenever the selection changes, so a toggled field is
  // always pre-filled with real content rather than something copied by
  // hand — and drop any previously-toggled fields/attachments, since they
  // described a different requirement's content.
  useEffect(() => {
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
      reviewerId: selectedRequirement.reviewer_id ?? "",
    });
    setCustomFieldValues(selectedRequirement.custom_fields);
    setChangedFields(new Set());
    setAttachmentFileIds([]);
    // `requirements` is a dependency, not just `requirementId`/`kind` — a
    // deep-linked requirement id can be set (by the effect above) before
    // the requirements list itself has finished loading, in which case
    // `selectedRequirement` is still null on that pass and this effect
    // must re-fire once the list actually arrives, not just on the next
    // `requirementId` change (which may never come).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requirementId, kind, requirements]);

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

  function resetForm() {
    setProposed(BLANK_PROPOSED);
    setChangedFields(new Set());
    setAttachmentFileIds([]);
    setCustomFieldValues({});
    setReason("");
    setShowForm(false);
    setCreateError(null);
  }

  async function createCr() {
    if (!projectId) return;
    setCreateError(null);
    try {
      if (kind === "modify_requirement") {
        await api.post(`/api/v1/projects/${projectId}/change-requests`, {
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
          proposed_reviewer_id: changedFields.has("reviewer_id") ? proposed.reviewerId || null : null,
          proposed_attachment_file_ids: changedFields.has("attachments") ? attachmentFileIds : [],
          custom_fields: changedFields.has("custom_fields") ? customFieldValues : {},
          reason,
        });
      } else {
        await api.post(`/api/v1/projects/${projectId}/change-requests`, {
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
          proposed_reviewer_id: proposed.reviewerId || null,
          reason,
          custom_fields: customFieldValues,
        });
      }
      resetForm();
      reload();
      showToast(strings.changeRequests.created);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : strings.common.error);
    }
  }

  function stageName(id: string | null) {
    return stages.find((s) => s.id === id)?.name ?? "—";
  }

  function requirementById(id: string | null) {
    return id ? requirements.find((r) => r.id === id) ?? null : null;
  }

  // A MODIFY_REQUIREMENT change request's proposed_* value is null for any
  // field not in `changed_fields` — fall back to the target requirement's
  // current value so the list/tile views never show a blank title.
  function crTitle(cr: ChangeRequest): string {
    if (cr.proposed_name) return cr.proposed_name;
    return requirementById(cr.requirement_id)?.name ?? changeRequestTerm;
  }

  function crTargetLabel(cr: ChangeRequest): string {
    if (cr.proposed_target_stage_id) return stageName(cr.proposed_target_stage_id);
    const requirement = requirementById(cr.requirement_id);
    return requirement ? stageName(requirement.target_stage_id) : "—";
  }

  function crLevelLabel(cr: ChangeRequest): string {
    if (cr.proposed_level) return REQUIREMENT_LEVEL_LABEL[cr.proposed_level];
    const requirement = requirementById(cr.requirement_id);
    return REQUIREMENT_LEVEL_LABEL[requirement?.level ?? "requirement"];
  }

  function toggleStatusFilter(status: ChangeRequestStatus) {
    setStatusFilter((current) => (current === status ? "" : status));
  }

  function toggleTargetStageFilter(stageId: string | null) {
    if (!stageId) return;
    setTargetStageFilter((current) => (current === stageId ? "" : stageId));
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
          <textarea
            className="input"
            rows={2}
            value={proposed.reasoning}
            onChange={(e) => setProposed((p) => ({ ...p, reasoning: e.target.value }))}
          />
        );
      case "clarification":
        return (
          <textarea
            className="input"
            rows={2}
            value={proposed.clarification}
            onChange={(e) => setProposed((p) => ({ ...p, clarification: e.target.value }))}
          />
        );
      case "description":
        return (
          <textarea
            className="input"
            rows={2}
            value={proposed.description}
            onChange={(e) => setProposed((p) => ({ ...p, description: e.target.value }))}
          />
        );
      case "target_stage_id":
        return (
          <select
            className="input"
            value={proposed.targetStageId}
            onChange={(e) => setProposed((p) => ({ ...p, targetStageId: e.target.value }))}
          >
            {stages.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        );
      case "level":
        return (
          <select
            className="input"
            value={proposed.level}
            onChange={(e) => setProposed((p) => ({ ...p, level: e.target.value as RequirementLevel }))}
          >
            <option value="requirement">{REQUIREMENT_LEVEL_LABEL.requirement}</option>
            <option value="recommended">{REQUIREMENT_LEVEL_LABEL.recommended}</option>
            <option value="optional">{REQUIREMENT_LEVEL_LABEL.optional}</option>
          </select>
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
          <select
            className="input"
            value={proposed.reviewerId}
            onChange={(e) => setProposed((p) => ({ ...p, reviewerId: e.target.value }))}
          >
            <option value="">{strings.reviews.unassigned}</option>
            {orgUsers.map((u) => (
              <option key={u.user_id} value={u.user_id}>
                {u.display_name} ({u.email})
              </option>
            ))}
          </select>
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
          <div className="stack" style={{ gap: "0.25rem" }}>
            {orgResources.length === 0 && (
              <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                {strings.changeRequests.noAttachmentsAvailable(orgLabel, orgLabelCap)}
              </p>
            )}
            {orgResources.map((r) => (
              <label key={r.id} className="row">
                <input type="checkbox" checked={attachmentFileIds.includes(r.id)} onChange={() => toggleAttachment(r.id)} />
                {r.filename}
              </label>
            ))}
          </div>
        );
      default:
        return null;
    }
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h1 style={{ margin: 0 }}>{strings.changeRequests.title}</h1>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          <Plus size={16} /> {strings.changeRequests.newChangeRequest}
        </button>
      </div>

      {showForm && (
        // Style guide "Pattern: modal dialog for entity create/rename" —
        // a brand-new entity opens in a Modal, not a permanently-visible
        // inline block that reflows the list underneath it.
        <Modal title={strings.changeRequests.newChangeRequest} onClose={() => setShowForm(false)} size="lg">
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
              <label className="stack" style={{ gap: "0.25rem" }}>
                {strings.changeRequests.selectARequirement}
                <select className="input" value={requirementId} onChange={(e) => setRequirementId(e.target.value)}>
                  {lockableRequirements.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.unique_code} — {r.name}
                    </option>
                  ))}
                </select>
              </label>
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
                  <div key={field} className="stack" style={{ gap: "0.35rem" }}>
                    <label className="row" style={{ gap: "0.5rem" }}>
                      <input type="checkbox" checked={changedFields.has(field)} onChange={() => toggleChangedField(field)} />
                      {CHANGEABLE_FIELD_LABEL[field]}
                    </label>
                    {changedFields.has(field) && <div style={{ marginLeft: "1.5rem" }}>{renderFieldEditor(field)}</div>}
                  </div>
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="row">
                <select
                  className="input"
                  value={componentId}
                  onChange={(e) => {
                    const nextComponentId = e.target.value;
                    setComponentId(nextComponentId);
                    setCategoryId(categories.find((c) => c.component_id === nextComponentId)?.id ?? "");
                  }}
                >
                  {components.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
                <select className="input" value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
                  {categories.filter((c) => c.component_id === componentId).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </div>
              <input
                className="input"
                placeholder={strings.changeRequests.proposedName}
                value={proposed.name}
                onChange={(e) => setProposed((p) => ({ ...p, name: e.target.value }))}
              />
              <textarea
                className="input"
                rows={2}
                placeholder={strings.changeRequests.proposedReasoning}
                value={proposed.reasoning}
                onChange={(e) => setProposed((p) => ({ ...p, reasoning: e.target.value }))}
              />
              <textarea
                className="input"
                rows={2}
                placeholder={strings.requirements.clarification}
                value={proposed.clarification}
                onChange={(e) => setProposed((p) => ({ ...p, clarification: e.target.value }))}
              />
              <textarea
                className="input"
                rows={2}
                placeholder={strings.requirements.description}
                value={proposed.description}
                onChange={(e) => setProposed((p) => ({ ...p, description: e.target.value }))}
              />
              <div className="row">
                <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
                  {strings.requirements.targetVersion}
                  <select
                    className="input"
                    value={proposed.targetStageId}
                    onChange={(e) => setProposed((p) => ({ ...p, targetStageId: e.target.value }))}
                  >
                    <option value="">—</option>
                    {stages.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="stack" style={{ gap: "0.25rem", flex: 1 }}>
                  {strings.requirements.level}
                  <select
                    className="input"
                    value={proposed.level}
                    onChange={(e) => setProposed((p) => ({ ...p, level: e.target.value as RequirementLevel }))}
                  >
                    <option value="requirement">{REQUIREMENT_LEVEL_LABEL.requirement}</option>
                    <option value="recommended">{REQUIREMENT_LEVEL_LABEL.recommended}</option>
                    <option value="optional">{REQUIREMENT_LEVEL_LABEL.optional}</option>
                  </select>
                </label>
              </div>
              <CustomFieldsForm
                definitions={customFieldDefs}
                values={customFieldValues}
                onChange={(fieldId, value) => setCustomFieldValues((v) => ({ ...v, [fieldId]: value }))}
              />
            </>
          )}

          <textarea
            className="input"
            rows={2}
            placeholder={strings.changeRequests.reason}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
          {createError && <div style={{ color: "var(--color-danger)" }}>{createError}</div>}
          <div className="row">
            <button
              className="btn btn-primary"
              onClick={createCr}
              disabled={
                !reason ||
                (kind === "modify_requirement"
                  ? !requirementId || changedFields.size === 0
                  : !proposed.name || !componentId || !categoryId)
              }
            >
              {strings.common.create}
            </button>
            {kind === "modify_requirement" && changedFields.size === 0 && (
              <span className="text-muted" style={{ fontSize: "0.85rem" }}>
                {strings.changeRequests.selectAtLeastOneField}
              </span>
            )}
          </div>
        </Modal>
      )}

      <div className="side-grid">
        <div className="stack">
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <ViewToggle mode={viewMode} onChange={setViewMode} />
          </div>

          {!crs && <Spinner />}
          {crs && crs.length === 0 && <p className="text-muted">{strings.changeRequests.empty}</p>}
          {crs && crs.length > 0 && viewMode === "list" && (
            <div className="card" style={{ overflowX: "auto" }}>
              <table>
                <thead>
                  <tr>
                    <SortableHeader
                      label="Name" sortKey="proposed_name" sort={sort}
                      onSort={(key) => setSort((s) => cycleSort(s, key))}
                    />
                    <SortableHeader
                      label={strings.changeRequests.status} sortKey="status" sort={sort}
                      onSort={(key) => setSort((s) => cycleSort(s, key))}
                    />
                    <th>Target</th>
                    <th>Level</th>
                    <SortableHeader
                      label="Created" sortKey="created_at" sort={sort}
                      onSort={(key) => setSort((s) => cycleSort(s, key))}
                    />
                  </tr>
                </thead>
                <tbody>
                  {crs.map((cr) => (
                    <tr key={cr.id}>
                      <td>
                        <Link to={`/projects/${projectId}/change-requests/${cr.id}`}>{crTitle(cr)}</Link>
                      </td>
                      <td>
                        <FilterBadge active={statusFilter === cr.status} onClick={() => toggleStatusFilter(cr.status)}>
                          {CHANGE_REQUEST_STATUS_LABEL[cr.status]}
                        </FilterBadge>
                      </td>
                      <td className="text-muted">{crTargetLabel(cr)}</td>
                      <td className="text-muted">{crLevelLabel(cr)}</td>
                      <td>{new Date(cr.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {crs && crs.length > 0 && viewMode === "tiles" && (
            <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(280px, 100%), 1fr))" }}>
              {crs.map((cr) => (
                <div key={cr.id} className="card stack" style={{ gap: "0.5rem" }}>
                  <Link to={`/projects/${projectId}/change-requests/${cr.id}`} style={{ fontWeight: 600 }}>
                    {crTitle(cr)}
                  </Link>
                  <div className="row" style={{ gap: "0.4rem" }}>
                    <FilterBadge active={statusFilter === cr.status} onClick={() => toggleStatusFilter(cr.status)}>
                      {CHANGE_REQUEST_STATUS_LABEL[cr.status]}
                    </FilterBadge>
                    {cr.proposed_target_stage_id && (
                      <FilterBadge
                        active={targetStageFilter === cr.proposed_target_stage_id}
                        onClick={() => toggleTargetStageFilter(cr.proposed_target_stage_id)}
                      >
                        {crTargetLabel(cr)}
                      </FilterBadge>
                    )}
                    <span className="badge">{crLevelLabel(cr)}</span>
                  </div>
                  <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                    {new Date(cr.created_at).toLocaleString()}
                  </div>
                </div>
              ))}
            </div>
          )}
          {crs && <LoadMoreButton loaded={crs.length} total={total} onClick={() => loadChangeRequests(crs.length, true)} />}
        </div>

        <FilterPanel>
          <h2 style={{ margin: 0, fontSize: "1rem" }}>Filters</h2>
          <FilterField label="Status">
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as CrStatusFilterValue)}>
              <option value="active">Active</option>
              <option value="">All statuses</option>
              {CR_STATUS_OPTIONS.map((s) => (
                <option key={s} value={s}>
                  {CHANGE_REQUEST_STATUS_LABEL[s]}
                </option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Target version">
            <select className="input" value={targetStageFilter} onChange={(e) => setTargetStageFilter(e.target.value)}>
              <option value="">All versions</option>
              {stages.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </FilterField>
        </FilterPanel>
      </div>
    </div>
  );
}
