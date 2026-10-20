import { useRecordCode } from "../hooks/useRecordCode";
import { Plus } from "lucide-react";
import { RecordCode } from "../components/RecordCode";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { DRAFT_ARTEFACT_ID, type CollectedLink } from "../api/artefactLinks";
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
  PrincipalRef,
  Project,
  ProjectStage,
  Requirement,
  RequirementLevel,
} from "../api/types";
import {
  CHANGE_REQUEST_STATUS_LABEL,
  CHANGE_REQUEST_STATUS_TONE,
  CHANGEABLE_FIELD_LABEL,
  CHANGEABLE_REQUIREMENT_FIELDS,
  ENTITY_ACCENT_COLOR,
  principalRef,
  REQUIREMENT_LEVEL_LABEL,
  savedPrincipalDisplay,
} from "../api/types";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { FilterBadge } from "../components/FilterBadge";
import { FilterField, FilterPanel } from "../components/FilterPanel";
import { ListPageLayout } from "../components/ListPageLayout";
import { TagFilterField } from "../components/TagFilterField";
import { useTagFilter } from "../hooks/useTagFilter";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { PrincipalPicker } from "../components/PrincipalPicker";
import { Modal } from "../components/Modal";
import { ProposedLinksEditor } from "../components/ProposedLinksEditor";
import { SortableHeader } from "../components/SortableHeader";
import { cycleSort, type SortState } from "../components/sortState";
import { Spinner } from "../components/Spinner";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { useOrgLabel, useOrgLabelCapitalized } from "../context/BrandingContext";
import { useStrings, useTerm } from "../context/TerminologyContext";
import { useToast } from "../context/ToastContext";
import { useLatest } from "../hooks/useLatest";
import { useRequestSequence } from "../hooks/useRequestSequence";
import { Badge } from "../components/Badge";
import { FormGrid, FormGridFull } from "../components/FormGrid";
import { CheckboxField, TextAreaField, TextField } from "../components/FormFields";
import { LabeledSelect } from "../components/LabeledSelect";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useProjectScope } from "../hooks/useProjectScope";
import { ProjectScopeFilter } from "../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../components/ProjectScopeLabel";
import { rowProjectId } from "../api/projectScope";
import { useResetOnChange } from "../hooks/useResetOnChange";

const PAGE_SIZE = 30;

const CR_STATUS_OPTIONS: ChangeRequestStatus[] = [
  "draft", "submitted", "in_review", "approved", "rejected", "withdrawn",
];

// Tri-state status filter — a change request list is
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
  reviewer: PrincipalRef | null;
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
  reviewer: null,
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
  const recordCode = useRecordCode();
  const { projectId } = useParams<{ projectId: string }>();
  const { showToast } = useToast();
  const [searchParams, setSearchParams] = useSearchParams();
  const [crs, setCrs] = useState<ChangeRequest[] | null>(null);
  const [total, setTotal] = useState(0);
  // Unfiltered mandatory-scope count — powers
  // `ResultCount` in `FilterPanel`'s header alongside `total` above, which
  // is the filtered count.
  const [totalUnfiltered, setTotalUnfiltered] = useState(0);
  const [requirements, setRequirements] = useState<Requirement[]>([]);
  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [organizationId, setOrganizationId] = useState<string | undefined>(undefined);
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
  // Links proposed with the request, created only if the approver merges them. They belong
  // to one requirement (or to the one a new request creates), so a different target starts over.
  const linksTarget = kind === "new_requirement" ? DRAFT_ARTEFACT_ID : requirementId;
  const [collectedLinks, setCollectedLinks] = useState<{ target: string; links: CollectedLink[] }>({ target: "", links: [] });
  const proposedLinks = collectedLinks.target === linksTarget ? collectedLinks.links : [];
  const setProposedLinks = (links: CollectedLink[]) => setCollectedLinks({ target: linksTarget, links });
  const [reason, setReason] = useState("");
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});
  const changeRequestTerm = useTerm("change_request");
  const [viewMode, setViewMode] = useViewMode("change-requests");
  // Seeded directly from the URL on initial render, not set in a separate
  // effect after mount (bug fix, 2026-08: dashboard glance navigation race
  // — same fix and reasoning as `RequirementsPage.tsx`'s identical
  // two-effect shape) — only one filter state, and therefore only one
  // fetch, ever exists per mount.
  const [statusFilter, setStatusFilter] = useState<CrStatusFilterValue>(
    () => (searchParams.get("status") as CrStatusFilterValue) || "active"
  );
  const [targetStageFilter, setTargetStageFilter] = useState("");
  // Free-text search (2026-10-04), server-side like the requirements list's,
  // so it finds a change request on any page of the paginated list.
  const [search, setSearch] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  // Column-header sorting — backend `sort`/
  // `order` param, same reasoning as `RequirementsPage.tsx`: this list is
  // already backend-paginated (`PAGE_SIZE`/`LoadMoreButton`), so a
  // client-side sort would only reorder the currently-loaded page.
  type ChangeRequestSortKey = "proposed_name" | "status" | "created_at";
  const [sort, setSort] = useState<SortState<ChangeRequestSortKey> | null>(null);
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (search) params.set("search", search);
    if (statusFilter === "active") params.set("active_only", "true");
    else if (statusFilter) params.set("cr_status", statusFilter);
    if (targetStageFilter) params.set("target_stage_id", targetStageFilter);
    for (const tag of tagFilter.tags) params.append("tag", tag);
    if (tagFilter.active) params.set("tag_mode", tagFilter.mode);
    if (projectScope.widened) params.set("project_scope", projectScope.scope);
    if (sort) {
      params.set("sort", sort.key);
      params.set("order", sort.direction);
    }
    return params;
  }

  // Read through a ref so a reload started from an older render (a
  // post-mutation `reload()` resuming after an `await`) still lists with the
  // filters the user has set since — otherwise, as the newest request, it
  // would overwrite their filtered results (found 2026-10-04 via the e2e
  // suite). Declared before the reload effect so it's current there.
  const listParamsRef = useLatest(listParams);

  // Belt-and-suspenders guard (bug fix, 2026-08: dashboard glance
  // navigation race), same reasoning as `RequirementsPage.tsx`'s identical
  // guard — discards a response if a newer request has since been kicked
  // off, covering any overlapping-fetch path beyond the mount-time race the
  // searchParams-seeding fix above eliminates (e.g. rapid filter changes).
  const beginLoad = useRequestSequence();

  async function loadChangeRequests(offset: number, append: boolean) {
    if (!projectId) return;
    const isLatest = beginLoad();
    const page = await api.getPage<ChangeRequest>(
      `/api/v1/projects/${projectId}/change-requests?${listParamsRef.current(offset).toString()}`
    );
    if (!isLatest()) return;
    setCrs((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
    setTotalUnfiltered(page.totalUnfiltered ?? page.total);
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
    // rejects a modify-CR against a still-draft/reviewed requirement, so defaulting to an unlocked one would
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
      setOrganizationId(proj.organization_id);
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

  useLoadOnChange(reload, [projectId, statusFilter, targetStageFilter, sort, search, tagFilter.query, projectScope.scope]);

  // Deep-linked from a requirement's "Make change request" button
  // (?requirement=<id>) — pre-selects that requirement for a
  // MODIFY_REQUIREMENT change request and opens the form.
  const deepLinkedRequirementId = searchParams.get("requirement");
  useResetOnChange([deepLinkedRequirementId], () => {
    if (deepLinkedRequirementId) {
      setKind("modify_requirement");
      setRequirementId(deepLinkedRequirementId);
      setShowForm(true);
    }
  }, { runOnMount: true });

  useEffect(() => {
    if (!deepLinkedRequirementId) return;
    setSearchParams((params) => {
      params.delete("requirement");
      return params;
    }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deepLinkedRequirementId]);

  // Deep-linked from the Project Overview dashboard's CR glance tiles/pie
  // chart segments (UX review) — `statusFilter` above is already seeded
  // straight from this same param on initial render (bug fix, 2026-08:
  // dashboard glance navigation race), so this effect only strips it from
  // the URL once; it must not call `setStatusFilter` itself, or the race
  // it was fixed to eliminate comes back.
  useEffect(() => {
    const status = searchParams.get("status");
    if (!status) return;
    setSearchParams((params) => {
      params.delete("status");
      return params;
    }, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);

  const selectedRequirement = requirements.find((r) => r.id === requirementId) ?? null;
  // A modify-CR can only target an already-locked (approved/completed)
  // requirement — offering an unlocked one in this dropdown
  // would just produce a 400 on submit.
  const lockableRequirements = requirements.filter((r) => r.is_locked);

  // Re-prime the proposed-value form from the newly-selected requirement's
  // current version whenever the selection changes, so a toggled field is
  // always pre-filled with real content rather than something copied by
  // hand — and drop any previously-toggled fields/attachments, since they
  // described a different requirement's content.
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
    // Keyed on the resolved requirement's id, not just `requirementId`/`kind`: a
    // deep-linked requirement id can be set before the requirements list has
    // finished loading, in which case `selectedRequirement` is still null on that
    // pass and the form must be primed once the list arrives.
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

  function resetForm() {
    setProposed(BLANK_PROPOSED);
    setChangedFields(new Set());
    setAttachmentFileIds([]);
    setProposedLinks([]);
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
          proposed_reviewer: changedFields.has("reviewer_id") ? proposed.reviewer : null,
          proposed_attachment_file_ids: changedFields.has("attachments") ? attachmentFileIds : [],
          custom_fields: changedFields.has("custom_fields") ? customFieldValues : {},
          proposed_links: proposedLinksPayload(),
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
          proposed_reviewer: proposed.reviewer,
          reason,
          custom_fields: customFieldValues,
          proposed_links: proposedLinksPayload(),
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
          <div className="stack" style={{ gap: "0.25rem" }}>
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

  return (
    <div className="stack">
      <ListPageLayout
        title={strings.changeRequests.title}
        actions={
          <button className="btn btn-primary" onClick={() => setShowForm(true)}>
            <Plus /> {strings.changeRequests.newChangeRequest}
          </button>
        }
        filter={
          <FilterPanel
            sectionKey="changeRequestsFilters"
            matching={total}
            total={totalUnfiltered}
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder={strings.changeRequests.search}
          >
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
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
          </FilterPanel>
        }
      >
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
                    <div key={field} className="stack" style={{ gap: "0.35rem" }}>
                      <label className="checkbox-label" style={{ gap: "0.5rem" }}>
                        <input type="checkbox" checked={changedFields.has(field)} onChange={() => toggleChangedField(field)} />
                        {CHANGEABLE_FIELD_LABEL[field]}
                      </label>
                      {changedFields.has(field) && <div style={{ marginLeft: "1.5rem" }}>{renderFieldEditor(field)}</div>}
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <FormGrid minColumn="18rem">
                <LabeledSelect helpNotNeeded required
                  label={strings.requirements.component}
                  value={componentId}
                  onChange={(nextComponentId) => {
                    setComponentId(nextComponentId);
                    setCategoryId(categories.find((c) => c.component_id === nextComponentId)?.id ?? "");
                  }}
                  options={components.map((c) => ({ value: c.id, label: c.name }))}
                  placeholder={null}
                />
                <LabeledSelect helpNotNeeded required
                  label={strings.requirements.category}
                  value={categoryId}
                  onChange={setCategoryId}
                  options={categories.filter((c) => c.component_id === componentId).map((c) => ({ value: c.id, label: c.name }))}
                  placeholder={null}
                />
                <FormGridFull>
                  <TextField helpNotNeeded required
                    label={strings.changeRequests.proposedName}
                    value={proposed.name}
                    onChange={(next) => setProposed((p) => ({ ...p, name: next }))}
                  />
                </FormGridFull>
                <FormGridFull>
                  <TextAreaField helpNotNeeded
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

            {projectId && linksTarget && (
              <ProposedLinksEditor
                projectId={projectId}
                artefactId={linksTarget}
                links={proposedLinks}
                onChange={setProposedLinks}
              />
            )}

            <TextAreaField helpNotNeeded required label={strings.changeRequests.reason} value={reason} onChange={setReason} />
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
                      <th>Code</th>
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
                      <tr
                        key={cr.id}
                        className="entity-accent-row"
                        style={{ ["--entity-accent-color" as string]: ENTITY_ACCENT_COLOR.change_request }}
                      >
                        <td className="text-muted"><RecordCode code={cr.unique_code} ownerProjectCode={cr.from_project_code} /></td>
                        <td>
                          <Link to={`/projects/${rowProjectId(cr, projectId ?? "")}/change-requests/${cr.id}`}>{crTitle(cr)}</Link>
                          <ProjectScopeLabel row={cr} />
                        </td>
                        <td>
                          <FilterBadge
                            active={statusFilter === cr.status}
                            tone={CHANGE_REQUEST_STATUS_TONE[cr.status]}
                            onClick={() => toggleStatusFilter(cr.status)}
                          >
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
                  <div
                    key={cr.id}
                    className="card stack entity-accent-card"
                    style={{ gap: "0.5rem", ["--entity-accent-color" as string]: ENTITY_ACCENT_COLOR.change_request }}
                  >
                    <Link to={`/projects/${rowProjectId(cr, projectId ?? "")}/change-requests/${cr.id}`} style={{ fontWeight: 600 }}>
                      {crTitle(cr)}
                    </Link>
                    <small className="text-muted"><RecordCode code={cr.unique_code} ownerProjectCode={cr.from_project_code} /></small>
                    <ProjectScopeLabel row={cr} />
                    <div className="row" style={{ gap: "0.4rem" }}>
                      <FilterBadge
                        active={statusFilter === cr.status}
                        tone={CHANGE_REQUEST_STATUS_TONE[cr.status]}
                        onClick={() => toggleStatusFilter(cr.status)}
                      >
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
                      <Badge>{crLevelLabel(cr)}</Badge>
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
      </ListPageLayout>
    </div>
  );
}
