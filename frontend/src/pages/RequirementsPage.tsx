import { useMutation } from "../hooks/useMutation";
import { ArrowDown, ArrowUp, GitPullRequest, MessageSquare, Plus, TriangleAlert } from "lucide-react";
import { RecordCode } from "../components/RecordCode";
import { useEffect, useRef, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  Category,
  Component,
  CustomFieldDefinition,
  FileAsset,
  OrgUser,
  Project,
  ProjectStage,
  Requirement,
  RequirementStatus,
} from "../api/types";
import type { CollectedLink } from "../api/artefactLinks";
import {
  ENTITY_ACCENT_COLOR,
  REQUIREMENT_LEVEL_LABEL,
  REQUIREMENT_STATUS_LABEL,
  REQUIREMENT_STATUS_TONE,
  principalRef,
} from "../api/types";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { CustomFieldsForm } from "../components/CustomFieldsForm";
import { RequirementFields } from "../components/RequirementFields";
import { EMPTY_REQUIREMENT_FIELDS, requirementPeopleAndReviewPayload, type RequirementFieldValues } from "../components/requirementFieldValues";
import { FileAttachmentList } from "../components/FileAttachmentList";
import { FilterBadge } from "../components/FilterBadge";
import { FilterCheckbox, FilterField, FilterPanel } from "../components/FilterPanel";
import { ListPageLayout } from "../components/ListPageLayout";
import { LoadMoreButton } from "../components/LoadMoreButton";
import { Popover } from "../components/Popover";
import { Modal } from "../components/Modal";
import { QuickLinkField } from "../components/QuickLinkField";
import { TagField } from "../components/TagField";
import { BulkTagDialog } from "../components/BulkTagDialog";
import { projectTagAdminApi } from "../api/tags";
import { TagFilterField } from "../components/TagFilterField";
import { SortableHeader } from "../components/SortableHeader";
import { cycleSort } from "../components/sortState";
import { Spinner } from "../components/Spinner";
import { useViewMode, ViewToggle } from "../components/ViewToggle";
import { useAuth } from "../context/AuthContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useMyProjectRoles } from "../hooks/useMyProjectRoles";
import { useLatest } from "../hooks/useLatest";
import { useRequestSequence } from "../hooks/useRequestSequence";
import { Badge } from "../components/Badge";
import { TextField } from "../components/FormFields";
import { LabeledSelect } from "../components/LabeledSelect";
import { FormGrid, FormGridFull } from "../components/FormGrid";
import { useCommitQuickLinks } from "../hooks/useCommitQuickLinks";
import { useCommitTags } from "../hooks/useCommitTags";
import { useTagFilter } from "../hooks/useTagFilter";
import { useLoadOnChange } from "../hooks/useLoadOnChange";
import { useProjectScope } from "../hooks/useProjectScope";
import { ProjectScopeFilter } from "../components/ProjectScopeFilter";
import { ProjectScopeLabel } from "../components/ProjectScopeLabel";
import { rowProjectId } from "../api/projectScope";
import { useResetOnChange } from "../hooks/useResetOnChange";
import { useRestoredRowCount } from "../hooks/useListPosition";
import { useUrlChoice, useUrlFlag, useUrlSort, useUrlText } from "../hooks/useUrlFilter";
import { addSharedListFilters } from "../utils/listFilterParams";

const PAGE_SIZE = 30;

// C-G-11: "completed" is no longer a `RequirementStatus` value — it's an
// independent overlay marker (`Requirement.is_completed`), filtered via its
// own `FilterCheckbox` below rather than a status option.
const STATUS_OPTIONS: RequirementStatus[] = ["draft", "reviewed", "approved", "archived"];
const SORT_KEYS = ["unique_code", "name", "status"] as const;

/**
 * Requirement browser (C-G-04: sorted by component/category), with search
 * by name/ID (U-E-01), a filter panel (status/target version/category/
 * comments/watched), scoping-stage-only reordering (C-E-03), and
 * incremental "load more" pagination (U-P-06) for large requirement sets.
 */
export function RequirementsPage() {
  const run = useMutation();
  const strings = useStrings();
  const { projectId } = useParams<{ projectId: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { user } = useAuth();
  const { showToast } = useToast();
  const commitQuickLinks = useCommitQuickLinks(projectId ?? "", "requirement");
  const commitTags = useCommitTags(projectId ?? "", "requirement");
  const tagFilter = useTagFilter();
  const projectScope = useProjectScope(projectId);
  const myRoles = useMyProjectRoles(projectId);
  const [isOrgAdminOfProject, setIsOrgAdminOfProject] = useState(false);
  const canManageProject =
    myRoles.includes("project_manager") || myRoles.includes("project_administrator") || isOrgAdminOfProject;
  const [requirements, setRequirements] = useState<Requirement[] | null>(null);
  const [total, setTotal] = useState(0);
  // Unfiltered mandatory-scope count — powers
  // `ResultCount` in `FilterPanel`'s header alongside `total` above, which
  // is the filtered/searched count.
  const [totalUnfiltered, setTotalUnfiltered] = useState(0);
  const [components, setComponents] = useState<Component[]>([]);
  const [categories, setCategories] = useState<Category[]>([]);
  // Both start empty before the first fetch resolves, which is
  // indistinguishable from "this project genuinely has none yet" — without
  // this flag, opening "New requirement" before that fetch completes
  // showed the quick-create-component/category inline form (meant only for
  // a genuinely empty project) at the same time as the real create form,
  // producing two ambiguous "Name" fields.
  const [metaLoaded, setMetaLoaded] = useState(false);
  const [stages, setStages] = useState<ProjectStage[]>([]);
  const [newInlineComponentName, setNewInlineComponentName] = useState("");
  const [newInlineComponentPrefix, setNewInlineComponentPrefix] = useState("");
  const [newInlineCategoryName, setNewInlineCategoryName] = useState("");
  const [newInlineCategoryPrefix, setNewInlineCategoryPrefix] = useState("");
  // The list's filters, search and sort live in the URL (`useUrlFilter`), so it comes back as it was left
  // after a visit to a record, and a dashboard glance links here with the same `status`, `stage` and
  // `completed` parameters. Completion is a separate overlay marker, not a status value.
  const [search, setSearch] = useUrlText("q");
  const [statusFilter, setStatusFilter] = useUrlChoice<RequirementStatus>("status", STATUS_OPTIONS);
  const [completedFilter, setCompletedFilter] = useUrlFlag("completed");
  const [targetStageFilter, setTargetStageFilter] = useUrlText("stage");
  const [categoryFilter, setCategoryFilter] = useUrlText("category");
  const [hasCommentsOnly, setHasCommentsOnly] = useUrlFlag("comments");
  const [onlyWatched, setOnlyWatched] = useUrlFlag("watched");
  // An archived requirement's detail page has the Restore button; this filter is how the list reaches one.
  const [includeArchived, setIncludeArchived] = useUrlFlag("archived");
  // The list is backend-paginated (`PAGE_SIZE`/`LoadMoreButton`), so sorting is a `sort`/`order` query
  // parameter the backend honours; sorting only the loaded rows would misrepresent the full-list order.
  const [sort, setSort] = useUrlSort(SORT_KEYS);
  const limitFor = useRestoredRowCount(PAGE_SIZE);
  const [showNewForm, setShowNewForm] = useState(false);
  const [newFields, setNewFields] = useState<RequirementFieldValues>(EMPTY_REQUIREMENT_FIELDS);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [newComponentId, setNewComponentId] = useState("");
  const [newCategoryId, setNewCategoryId] = useState("");
  const [customFieldDefs, setCustomFieldDefs] = useState<CustomFieldDefinition[]>([]);
  const [customFieldValues, setCustomFieldValues] = useState<Record<string, unknown>>({});
  const [viewMode, setViewMode] = useViewMode("requirements");
  const [project, setProject] = useState<Project | null>(null);

  // --- Create-modal step 2: attach files to the just-created requirement
  // (UX review — previously only possible after closing the modal and
  // opening the detail page). Mirrors RequirementDetailPage's own files
  // state and handlers, scoped to `createdRequirement`. Links are chosen
  // in step 1 with the shared quick-link field and created with the record. ---
  const [createdRequirement, setCreatedRequirement] = useState<Requirement | null>(null);
  const [createdFiles, setCreatedFiles] = useState<FileAsset[]>([]);
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [newTags, setNewTags] = useState<string[]>([]);

  // --- Bulk operations (list view only) ---------------------------------
  // Style guide "Pattern: bulk operations on a list" — the first pilot of
  // this shape in the app. Selection is a plain `id` Set rather than tied to array
  // indices, so it survives `loadRequirements`'s append-on-"load more"
  // without extra bookkeeping, and "select all" only ever means "all
  // currently loaded rows" (U-P-06's incremental pagination makes a true
  // "all 500 matching the filter" unsafe to promise from the client).
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkArchiveDialogOpen, setBulkArchiveDialogOpen] = useState(false);
  const [bulkMovePopoverOpen, setBulkMovePopoverOpen] = useState(false);
  const [bulkTagDialogOpen, setBulkTagDialogOpen] = useState(false);
  const [bulkMoveStageId, setBulkMoveStageId] = useState("");
  const [bulkMoveDialogOpen, setBulkMoveDialogOpen] = useState(false);
  const bulkMoveTriggerRef = useRef<HTMLButtonElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);

  /** The list's filters, by the names its list request and the shared export both take (no paging or sort). */
  function filterParams(): URLSearchParams {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (statusFilter) params.set("status", statusFilter);
    if (completedFilter) params.set("is_completed", "true");
    if (targetStageFilter) params.set("target_stage_id", targetStageFilter);
    if (categoryFilter) params.set("category_id", categoryFilter);
    if (hasCommentsOnly) params.set("has_comments", "true");
    if (onlyWatched) params.set("only_watched", "true");
    if (includeArchived) params.set("include_archived", "true");
    addSharedListFilters(params, tagFilter, projectScope);
    return params;
  }

  function listParams(offset: number): URLSearchParams {
    const params = new URLSearchParams({ limit: String(limitFor(offset)), offset: String(offset) });
    filterParams().forEach((value, key) => params.append(key, value));
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
  // navigation race) alongside the filters living in the URL — neither
  // `loadRequirements` nor `reload()` previously sequenced requests at all,
  // so *any* path that can fire two overlapping fetches (e.g. rapid filter
  // changes, not just the mount-time race the seeding fix eliminates) could
  // still let a slower, stale response overwrite a faster, newer one. Each
  // call claims the next id; a response is applied only if no newer call
  // has started since.
  const beginLoad = useRequestSequence();

  async function loadRequirements(offset: number, append: boolean) {
    if (!projectId) return;
    const isLatest = beginLoad();
    const page = await api.getPage<Requirement>(
      `/api/v1/projects/${projectId}/requirements?${listParamsRef.current(offset).toString()}`
    );
    if (!isLatest()) return;
    setRequirements((prev) => (append && prev ? [...prev, ...page.items] : page.items));
    setTotal(page.total);
    setTotalUnfiltered(page.totalUnfiltered ?? page.total);
  }

  async function reload() {
    if (!projectId) return;
    setRequirements(null);
    // A fresh load invalidates any prior selection (a filter/search change,
    // or the post-bulk-op reload below, may drop previously-selected rows
    // from the result set entirely) — "load more" append, by contrast,
    // calls `loadRequirements` directly and never touches this.
    setSelectedIds(new Set());
    const [comps, cats, stgs, defs] = await Promise.all([
      api.get<Component[]>(`/api/v1/projects/${projectId}/components`),
      api.get<Category[]>(`/api/v1/projects/${projectId}/categories`),
      api.get<ProjectStage[]>(`/api/v1/projects/${projectId}/stages`),
      api.get<CustomFieldDefinition[]>(`/api/v1/projects/${projectId}/custom-fields?entity_kind=requirement`),
      loadRequirements(0, false),
    ]);
    setComponents(comps);
    setCategories(cats);
    setStages(stgs);
    setCustomFieldDefs(defs);
    // Target is mandatory (it can never be left unset) — the select always
    // has a real stage pre-filled, never a blank "—" option, same as the
    // backend's own create-time default (routers/requirements.py).
    if (!newFields.targetStageId && stgs[0]) setNewFields((f) => (f.targetStageId ? f : { ...f, targetStageId: stgs[0].id }));
    const selectedComponentId = newComponentId || comps[0]?.id || "";
    if (!newComponentId && comps[0]) setNewComponentId(comps[0].id);
    // Must belong to the selected component (the tree) — picking any
    // project-wide first category could silently mismatch it.
    if (!newCategoryId) {
      const firstOwnCategory = cats.find((c) => c.component_id === selectedComponentId);
      if (firstOwnCategory) setNewCategoryId(firstOwnCategory.id);
    }
    setMetaLoaded(true);
  }

  useLoadOnChange(reload, [
    projectId, search, statusFilter, completedFilter, targetStageFilter, categoryFilter,
    hasCommentsOnly, onlyWatched, includeArchived, sort, tagFilter.query, projectScope.scope,
  ]);

  // Deep-linked from the Project Overview page's "New requirement" button
  // (?new=1) — opened once, then the param is stripped so a later reload
  // of this page doesn't keep reopening the form.
  const newFormRequested = searchParams.get("new") === "1";
  useResetOnChange([newFormRequested], () => {
    if (newFormRequested) setShowNewForm(true);
  }, { runOnMount: true });

  useEffect(() => {
    if (!newFormRequested) return;
    setSearchParams((params) => {
      params.delete("new");
      return params;
    }, { replace: true });
  }, [newFormRequested, setSearchParams]);

  useEffect(() => {
    if (!projectId || !user) return;
    (async () => {
      try {
        const proj = await api.get<Project>(`/api/v1/projects/${projectId}`);
        setProject(proj);
        const users = await api.get<OrgUser[]>(`/api/v1/orgs/${proj.organization_id}/users`);
        setOrgUsers(users);
        setIsOrgAdminOfProject(users.some((u) => u.user_id === user.id && u.roles.includes("org_admin")));
      } catch {
        // No org role at all (rare) — canManageProject still resolves correctly
        // from myRoles alone in that case.
      }
    })();
  }, [projectId, user]);

  async function createInlineComponent() {
    if (!projectId || !newInlineComponentName || !newInlineComponentPrefix) return;
    try {
      await api.post(`/api/v1/projects/${projectId}/components`, {
        name: newInlineComponentName,
        prefix: newInlineComponentPrefix,
      });
      setNewInlineComponentName("");
      setNewInlineComponentPrefix("");
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function createInlineCategory() {
    if (!projectId || !newInlineCategoryName || !newInlineCategoryPrefix || !newComponentId) return;
    try {
      await api.post(`/api/v1/projects/${projectId}/categories`, {
        name: newInlineCategoryName,
        prefix: newInlineCategoryPrefix,
        component_id: newComponentId,
      });
      setNewInlineCategoryName("");
      setNewInlineCategoryPrefix("");
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  /**
   * `andAttach`: when true (the "Create & attach files" action, UX
   * review — attaching should be possible during creation, not only
   * afterwards from the detail page), the modal advances to a second step
   * against the just-created requirement's real id instead of closing —
   * the backend's file endpoints require an existing id, so this
   * reuses them rather than building a pre-create staging flow. The plain
   * "Create" action keeps closing the modal immediately, unchanged — most
   * creates don't need an attachment, and every existing workflow (the
   * golden path included) depends on that one-click-and-back-to-the-list
   * behaviour, so the extra step is opt-in rather than forced on every create.
   */
  async function createRequirement(andAttach: boolean) {
    if (!projectId || !newComponentId || !newCategoryId || !newFields.targetStageId) return;
    try {
      const created = await api.post<Requirement>(`/api/v1/projects/${projectId}/requirements`, {
        name: newFields.name,
        reasoning: newFields.reasoning,
        clarification: newFields.clarification,
        description: newFields.description,
        component_id: newComponentId,
        category_id: newCategoryId,
        target_stage_id: newFields.targetStageId,
        level: newFields.level,
        ...requirementPeopleAndReviewPayload(newFields),
        keywords: [],
        custom_fields: customFieldValues,
      });
      setNewFields((f) => ({ ...EMPTY_REQUIREMENT_FIELDS, targetStageId: f.targetStageId }));
      setCustomFieldValues({});
      reload();
      showToast(strings.requirements.created);
      await commitQuickLinks(created.id, quickLinks);
      setQuickLinks([]);
      await commitTags(created.id, newTags);
      setNewTags([]);
      if (!andAttach) {
        setShowNewForm(false);
        return;
      }
      setCreatedRequirement(created);
      setCreatedFiles([]);
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  async function uploadCreatedRequirementFile(file: File) {
    if (!projectId || !createdRequirement) return;
    if (!(await run(() => api.postFile(`/api/v1/projects/${projectId}/requirements/${createdRequirement.id}/files`, file), "upload", "file"))) return;
    setCreatedFiles(await api.get<FileAsset[]>(`/api/v1/projects/${projectId}/requirements/${createdRequirement.id}/files`));
  }

  async function removeCreatedRequirementFile(fileId: string) {
    if (!projectId || !createdRequirement) return;
    if (!(await run(() => api.delete(`/api/v1/projects/${projectId}/requirements/${createdRequirement.id}/files/${fileId}`), "remove", "file"))) return;
    setCreatedFiles(await api.get<FileAsset[]>(`/api/v1/projects/${projectId}/requirements/${createdRequirement.id}/files`));
  }

  function finishCreateRequirement() {
    setShowNewForm(false);
    setCreatedRequirement(null);
    reload();
  }

  async function move(id: string, direction: "up" | "down") {
    try {
      await api.post(`/api/v1/projects/${projectId}/requirements/${id}/move`, { direction });
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  // `indeterminate` isn't a settable HTML attribute/React prop — it's a
  // DOM-only property, so the "some but not all loaded rows selected"
  // visual state has to be applied imperatively via the ref, same as any
  // other indeterminate-checkbox implementation.
  useEffect(() => {
    if (!selectAllRef.current || !requirements) return;
    const own = requirements.filter((r) => !r.from_project_id);
    const selectedLoaded = own.filter((r) => selectedIds.has(r.id)).length;
    selectAllRef.current.indeterminate = selectedLoaded > 0 && selectedLoaded < own.length;
  }, [requirements, selectedIds]);

  function toggleRowSelected(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleSelectAllLoaded() {
    if (!requirements) return;
    // Rows from a related project are read-only here: bulk actions only ever touch this project's own.
    const own = requirements.filter((r) => !r.from_project_id);
    setSelectedIds((current) => {
      const allSelected = own.every((r) => current.has(r.id));
      return allSelected ? new Set() : new Set(own.map((r) => r.id));
    });
  }

  /** Runs `action` once per selected requirement, sequentially (simpler
   * than bounded concurrency and fine for the list sizes this pilot
   * targets), tolerating individual failures rather than aborting the
   * whole batch — one locked/already-archived row shouldn't block the
   * rest. Reports a CSV-import-wizard-style "N updated"/"N updated, M
   * failed" summary via the shared `Toast`, then clears the selection and
   * refreshes the list regardless of outcome. */
  async function runBulkAction(action: (r: Requirement) => Promise<void>) {
    if (!requirements) return;
    const targets = requirements.filter((r) => selectedIds.has(r.id));
    setBulkRunning(true);
    let succeeded = 0;
    let failed = 0;
    for (const r of targets) {
      try {
        await action(r);
        succeeded++;
      } catch {
        failed++;
      }
    }
    setBulkRunning(false);
    setBulkMoveStageId("");
    reload();
    if (failed > 0) {
      showToast(strings.requirements.bulkResultPartial(succeeded, failed), "error");
    } else {
      showToast(strings.requirements.bulkResultSuccess(succeeded));
    }
  }

  async function bulkArchive() {
    setBulkArchiveDialogOpen(false);
    await runBulkAction((r) => api.delete(`/api/v1/projects/${projectId}/requirements/${r.id}`));
  }

  async function bulkMoveToStage() {
    setBulkMoveDialogOpen(false);
    const targetStageId = bulkMoveStageId;
    // Mirrors `RequirementDetailPage.tsx`'s own `save()` payload exactly
    // (the direct-edit `PUT` endpoint requires the full `RequirementUpdate`
    // shape, not a partial patch) — every field except `target_stage_id`
    // carries the row's own current value forward unchanged, so the only
    // effective change is the stage.
    await runBulkAction((r) =>
      api.put(`/api/v1/projects/${projectId}/requirements/${r.id}`, {
        name: r.name,
        reasoning: r.reasoning,
        clarification: r.clarification,
        description: r.description,
        component_id: r.component_id,
        category_id: r.category_id,
        owner: principalRef(r.owner),
        target_stage_id: targetStageId,
        level: r.level,
        custom_fields: r.custom_fields,
        change_note: "Bulk move to stage.",
        review_date: r.review_date,
        review_lead_days: r.review_lead_days,
        reviewer: principalRef(r.reviewer),
      })
    );
  }

  function componentName(id: string) {
    return components.find((c) => c.id === id)?.name ?? "";
  }
  function categoryName(id: string) {
    return categories.find((c) => c.id === id)?.name ?? "";
  }
  function stageName(id: string | null) {
    return stages.find((s) => s.id === id)?.name ?? "—";
  }

  function toggleStatusFilter(status: RequirementStatus) {
    setStatusFilter((current) => (current === status ? "" : status));
  }

  function badges(r: Requirement) {
    return (
      <>
        {r.comment_count > 0 && (
          <span className="row" title={`${r.comment_count} comment(s)`} style={{ gap: "0.2rem" }}>
            <MessageSquare size={14} /> {r.comment_count}
          </span>
        )}
        {r.has_open_change_request && (
          <span title="Has a pending change request">
            <GitPullRequest size={14} />
          </span>
        )}
        {r.requires_approval && (
          <span title="Requires approval">
            <TriangleAlert size={14} />
          </span>
        )}
      </>
    );
  }

  return (
    <div className="stack">
      <ListPageLayout
        title={strings.requirements.title}
        ready={requirements !== null}
        loadedRows={requirements?.length}
        actions={
          <button className="btn btn-primary" onClick={() => setShowNewForm(true)}>
            <Plus size={16} /> {strings.requirements.newRequirement}
          </button>
        }
        records={{ projectId: projectId ?? "", recordType: "requirement", filters: filterParams().toString(), onImported: reload }}
        filter={
          <FilterPanel
            sectionKey="requirementsFilters"
            matching={total}
            total={totalUnfiltered}
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder={strings.requirements.search}
          >
            <FilterField label="Status">
              <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as RequirementStatus | "")}>
                <option value="">All statuses</option>
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s}>
                    {REQUIREMENT_STATUS_LABEL[s]}
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
            <FilterField label={strings.requirements.category}>
              <select className="input" value={categoryFilter} onChange={(e) => setCategoryFilter(e.target.value)}>
                <option value="">{strings.requirements.allCategories}</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </FilterField>
            {/* C-G-11: completion is now an independent overlay marker, not a
                status value — a separate checkbox alongside the Status
                <select> above rather than one of its options. */}
            <ProjectScopeFilter scope={projectScope} />
            {projectId && <TagFilterField projectId={projectId} filter={tagFilter} />}
            <FilterCheckbox label={strings.requirements.completedFilter} checked={completedFilter} onChange={setCompletedFilter} />
            <FilterCheckbox label="Has comments" checked={hasCommentsOnly} onChange={setHasCommentsOnly} />
            <FilterCheckbox label="Only watched" checked={onlyWatched} onChange={setOnlyWatched} />
            <FilterCheckbox label={strings.requirements.includeArchived} checked={includeArchived} onChange={setIncludeArchived} />
          </FilterPanel>
        }
      >

        {showNewForm && metaLoaded && (
          // Style guide "Pattern: modal dialog for entity create/rename" —
          // a brand-new entity opens in a Modal, not a layer that still
          // occupies the side panel's "detail about the current view" slot.
          <Modal
            title={createdRequirement
              ? `${createdRequirement.unique_code} — ${strings.requirements.attachFilesAndLinks}`
              : strings.requirements.newRequirement}
            onClose={finishCreateRequirement}
            size="lg"
          >
            {createdRequirement ? (
              <>
                <div className="stack">
                  <h3 style={{ margin: 0, fontSize: "1rem" }}>{strings.requirements.attachments}</h3>
                  <FileAttachmentList
                    files={createdFiles}
                    onUpload={uploadCreatedRequirementFile}
                    onRemove={removeCreatedRequirementFile}
                  />
                </div>
                <div className="row" style={{ justifyContent: "flex-end" }}>
                  <button className="btn btn-primary" onClick={finishCreateRequirement}>
                    {strings.requirements.finish}
                  </button>
                </div>
              </>
            ) : components.length === 0 || categories.length === 0 ? (
              <>
                <p style={{ margin: 0 }}>{strings.requirements.noComponentsOrCategories}</p>
                {canManageProject ? (
                  <div className="stack">
                    {components.length === 0 && (
                      <div className="row" style={{ alignItems: "flex-end" }}>
                        <TextField helpNotNeeded label={strings.admin.name} value={newInlineComponentName} onChange={setNewInlineComponentName} />
                        <TextField help={strings.help.requirementPrefix}
                          label={strings.admin.prefix}
                          value={newInlineComponentPrefix}
                          onChange={(next) => setNewInlineComponentPrefix(next.toUpperCase())}
                          inputProps={{ style: { maxWidth: 100 } }}
                        />
                        <button
                          className="btn btn-primary"
                          onClick={createInlineComponent}
                          disabled={!newInlineComponentName || !newInlineComponentPrefix}
                        >
                          <Plus /> {strings.admin.newComponent}
                        </button>
                      </div>
                    )}
                    {categories.length === 0 && components.length > 0 && (
                      <div className="row" style={{ alignItems: "flex-end" }}>
                        {components.length > 1 && (
                          <LabeledSelect helpNotNeeded
                            label={strings.requirements.component}
                            value={newComponentId}
                            onChange={setNewComponentId}
                            options={components.map((c) => ({ value: c.id, label: c.name }))}
                            placeholder={null}
                          />
                        )}
                        <TextField helpNotNeeded label={strings.admin.name} value={newInlineCategoryName} onChange={setNewInlineCategoryName} />
                        <TextField help={strings.help.requirementPrefix}
                          label={strings.admin.prefix}
                          value={newInlineCategoryPrefix}
                          onChange={(next) => setNewInlineCategoryPrefix(next.toUpperCase())}
                          inputProps={{ style: { maxWidth: 100 } }}
                        />
                        <button
                          className="btn btn-primary"
                          onClick={createInlineCategory}
                          disabled={!newInlineCategoryName || !newInlineCategoryPrefix}
                        >
                          <Plus /> {strings.admin.newCategory}
                        </button>
                      </div>
                    )}
                  </div>
                ) : (
                  <Link to={`/projects/${projectId}/admin`} className="btn btn-primary" style={{ alignSelf: "flex-start" }}>
                    {strings.requirements.configureComponentsFirst}
                  </Link>
                )}
              </>
            ) : (
              <>
                <FormGrid minColumn="18rem">
                  <RequirementFields
                    values={newFields}
                    onChange={setNewFields}
                    stages={stages}
                    orgUsers={orgUsers}
                    organizationId={project?.organization_id}
                    projectId={projectId}
                    ownerPlaceholder={strings.requirements.ownerDefaultsToYou}
                    afterDescription={
                      <>
                        <LabeledSelect helpNotNeeded required
                          label={strings.requirements.component}
                          value={newComponentId}
                          onChange={(componentId) => {
                            setNewComponentId(componentId);
                            // Category is nested under one component (the tree) — a
                            // category belonging to the previously-selected component
                            // is never valid once the component changes.
                            const firstOwnCategory = categories.find((c) => c.component_id === componentId);
                            setNewCategoryId(firstOwnCategory?.id ?? "");
                          }}
                          options={components.map((c) => ({ value: c.id, label: `${c.name} (${c.prefix})` }))}
                          placeholder={null}
                        />
                        <LabeledSelect helpNotNeeded required
                          label={strings.requirements.category}
                          value={newCategoryId}
                          onChange={setNewCategoryId}
                          options={categories
                            .filter((c) => c.component_id === newComponentId)
                            .map((c) => ({ value: c.id, label: `${c.name} (${c.prefix})` }))}
                          placeholder={categories.some((c) => c.component_id === newComponentId) ? null : strings.requirements.noCategoriesForComponent}
                        />
                      </>
                    }
                  />
                  <FormGridFull>
                    <CustomFieldsForm
                      definitions={customFieldDefs}
                      values={customFieldValues}
                      onChange={(fieldId, value) => setCustomFieldValues((v) => ({ ...v, [fieldId]: value }))}
                    />
                  </FormGridFull>
                  <FormGridFull>
                    <QuickLinkField projectId={projectId ?? ""} artefactType="requirement" value={quickLinks} onChange={setQuickLinks} />
                  </FormGridFull>
                  <FormGridFull>
                    <TagField projectId={projectId ?? ""} artefactType="requirement" value={newTags} onChange={setNewTags} />
                  </FormGridFull>
                </FormGrid>
                <div className="row" style={{ justifyContent: "flex-end" }}>
                  <button
                    className="btn"
                    onClick={() => createRequirement(true)}
                    disabled={!newFields.name || !newComponentId || !newCategoryId || !newFields.targetStageId}
                  >
                    {strings.requirements.createAndAttach}
                  </button>
                  <button
                    className="btn btn-primary"
                    onClick={() => createRequirement(false)}
                    disabled={!newFields.name || !newComponentId || !newCategoryId || !newFields.targetStageId}
                  >
                    {strings.common.create}
                  </button>
                </div>
              </>
            )}
          </Modal>
        )}
          <div className="stack">
            <div className="row" style={{ justifyContent: "flex-end" }}>
              <ViewToggle mode={viewMode} onChange={setViewMode} />
            </div>

            {/* Bulk operations toolbar (style guide "Pattern: bulk operations
                on a list") — table/list view only, per this pilot's scope;
                tile view has no checkbox column to select from. Sits directly
                above the table rather than replacing the search/view-toggle
                row above, so it's visible without scrolling away from the
                list it acts on. Gated on `canManageProject` the same way the
                checkbox column itself is (see below) — both bulk actions
                require the same manager/administrator role the single-row
                Archive button already requires on `RequirementDetailPage.tsx`. */}
            {viewMode === "list" && canManageProject && selectedIds.size > 0 && (
              <div className="card row" style={{ justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: "var(--space-3)" }}>
                <div className="row" style={{ gap: "var(--space-4)", alignItems: "center" }}>
                  <strong>{strings.requirements.bulkSelectedCount(selectedIds.size)}</strong>
                  <button className="btn" onClick={() => setSelectedIds(new Set())} disabled={bulkRunning}>
                    {strings.requirements.bulkClearSelection}
                  </button>
                </div>
                <div className="row" style={{ gap: "var(--space-3)" }}>
                  <button className="btn" onClick={() => setBulkTagDialogOpen(true)} disabled={bulkRunning}>
                    {strings.requirements.bulkTagSelected}
                  </button>
                  <button className="btn btn-danger" onClick={() => setBulkArchiveDialogOpen(true)} disabled={bulkRunning}>
                    {strings.requirements.bulkArchiveSelected}
                  </button>
                  <button
                    ref={bulkMoveTriggerRef}
                    className="btn"
                    onClick={() => {
                      setBulkMoveStageId((current) => current || stages[0]?.id || "");
                      setBulkMovePopoverOpen((v) => !v);
                    }}
                    disabled={bulkRunning || stages.length === 0}
                  >
                    {strings.requirements.bulkMoveToStage}
                  </button>
                  {bulkMovePopoverOpen && (
                    <Popover anchorRef={bulkMoveTriggerRef} title={strings.requirements.bulkMoveToStage} onClose={() => setBulkMovePopoverOpen(false)}>
                      <div className="stack" style={{ gap: "var(--space-3)", minWidth: 200 }}>
                        <select
                          className="input"
                          aria-label={strings.requirements.targetVersion}
                          value={bulkMoveStageId}
                          onChange={(e) => setBulkMoveStageId(e.target.value)}
                        >
                          {stages.map((s) => (
                            <option key={s.id} value={s.id}>
                              {s.name}
                            </option>
                          ))}
                        </select>
                        <button
                          className="btn btn-primary"
                          disabled={!bulkMoveStageId}
                          onClick={() => {
                            setBulkMovePopoverOpen(false);
                            setBulkMoveDialogOpen(true);
                          }}
                        >
                          {strings.requirements.bulkMoveApply}
                        </button>
                      </div>
                    </Popover>
                  )}
                </div>
              </div>
            )}

            {bulkArchiveDialogOpen && (
              <ConfirmDialog
                title={strings.requirements.bulkArchiveTitle(selectedIds.size)}
                message={strings.requirements.bulkArchiveConfirm}
                confirmLabel={strings.requirements.bulkArchiveSelected}
                onConfirm={bulkArchive}
                onCancel={() => setBulkArchiveDialogOpen(false)}
              />
            )}

            {bulkTagDialogOpen && projectId && (
              <BulkTagDialog
                api={projectTagAdminApi(projectId)}
                artefactType="requirement"
                ids={[...selectedIds]}
                title={strings.requirements.bulkTagTitle(selectedIds.size)}
                onClose={() => setBulkTagDialogOpen(false)}
                onApplied={async (result) => {
                  setBulkTagDialogOpen(false);
                  showToast(strings.tags.admin.reclassifyDone(result.matched));
                  await reload();
                }}
              />
            )}

            {bulkMoveDialogOpen && (
              <ConfirmDialog
                title={strings.requirements.bulkMoveTitle(selectedIds.size, stageName(bulkMoveStageId))}
                message={strings.requirements.bulkMoveConfirm}
                confirmLabel={strings.requirements.bulkMoveApply}
                onConfirm={bulkMoveToStage}
                onCancel={() => setBulkMoveDialogOpen(false)}
              />
            )}

            {!requirements && <Spinner />}
            {requirements && requirements.length === 0 && <p className="text-muted">{strings.requirements.empty}</p>}
            {requirements && requirements.length > 0 && viewMode === "tiles" && (
              <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(min(280px, 100%), 1fr))" }}>
                {requirements.map((r) => (
                  <div
                    key={r.id}
                    className="card stack entity-accent-card"
                    style={{ gap: "var(--space-3)", ["--entity-accent-color" as string]: ENTITY_ACCENT_COLOR.requirement }}
                  >
                    <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
                      <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                        <RecordCode code={r.unique_code} ownerProjectCode={r.from_project_code} />
                      </span>
                      {!r.from_project_id && (
                        <div className="row" style={{ gap: "var(--space-1)" }}>
                          <button className="btn" onClick={() => move(r.id, "up")} title={strings.common.up} aria-label={strings.common.up}>
                            <ArrowUp />
                          </button>
                          <button className="btn" onClick={() => move(r.id, "down")} title={strings.common.down} aria-label={strings.common.down}>
                            <ArrowDown />
                          </button>
                        </div>
                      )}
                    </div>
                    <Link to={`/projects/${rowProjectId(r, projectId ?? "")}/requirements/${r.id}`} style={{ fontWeight: 600 }}>
                      {r.name}
                    </Link>
                    <ProjectScopeLabel row={r} />
                    {r.reasoning && (
                      <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
                        {r.reasoning.length > 140 ? `${r.reasoning.slice(0, 140)}…` : r.reasoning}
                      </p>
                    )}
                    <div className="row" style={{ justifyContent: "space-between" }}>
                      <div className="row" style={{ gap: "var(--space-2)" }}>
                        <FilterBadge
                          active={statusFilter === r.status}
                          tone={REQUIREMENT_STATUS_TONE[r.status]}
                          onClick={() => toggleStatusFilter(r.status)}
                        >
                          {REQUIREMENT_STATUS_LABEL[r.status]}
                        </FilterBadge>
                        {/* C-G-11: rendered as its own badge, distinct from
                            the status badge above (which stays "Approved"
                            for a completed requirement) — completion is now
                            an independent overlay, not a merged status. */}
                        {r.is_completed && <Badge>{strings.requirements.completedBadge}</Badge>}
                        {r.is_locked && <Badge>{strings.requirements.locked}</Badge>}
                        {r.is_archived && <Badge>{strings.requirements.archivedBadge}</Badge>}
                      </div>
                      <div className="row" style={{ gap: "var(--space-3)" }}>{badges(r)}</div>
                    </div>
                    <div className="text-muted" style={{ fontSize: "0.85rem" }}>
                      {r.from_project_id ? "—" : `${componentName(r.component_id)} · ${categoryName(r.category_id)}`}
                    </div>
                    <div className="text-muted" style={{ fontSize: "0.8rem" }}>
                      Target: {r.from_project_id ? "—" : stageName(r.target_stage_id)} · Level: {REQUIREMENT_LEVEL_LABEL[r.level]}
                    </div>
                  </div>
                ))}
              </div>
            )}
            {requirements && requirements.length > 0 && viewMode === "list" && (
              <div className="card" style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      {canManageProject && (
                        <th style={{ width: "3%" }}>
                          <input
                            ref={selectAllRef}
                            type="checkbox"
                            checked={requirements.some((r) => !r.from_project_id) && requirements.every((r) => r.from_project_id || selectedIds.has(r.id))}
                            onChange={toggleSelectAllLoaded}
                            aria-label={strings.requirements.bulkSelectAll}
                          />
                        </th>
                      )}
                      <SortableHeader
                        style={{ width: "9%" }} label="ID" sortKey="unique_code" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                      <SortableHeader
                        style={{ width: "38%" }} label="Name" sortKey="name" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                      <SortableHeader
                        label={strings.changeRequests.status} sortKey="status" sort={sort}
                        onSort={(key) => setSort((s) => cycleSort(s, key))}
                      />
                      <th>Target · level</th>
                      <th>Component · category</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {requirements.map((r) => (
                      <tr
                        key={r.id}
                        className="entity-accent-row"
                        style={{ ["--entity-accent-color" as string]: ENTITY_ACCENT_COLOR.requirement }}
                      >
                        {canManageProject && (
                          <td>
                            {!r.from_project_id && (
                              <input
                                type="checkbox"
                                checked={selectedIds.has(r.id)}
                                onChange={() => toggleRowSelected(r.id)}
                                aria-label={strings.requirements.bulkSelectRow(`${r.unique_code} ${r.name}`)}
                              />
                            )}
                          </td>
                        )}
                        <td className="text-muted"><RecordCode code={r.unique_code} ownerProjectCode={r.from_project_code} /></td>
                        <td>
                          <Link to={`/projects/${rowProjectId(r, projectId ?? "")}/requirements/${r.id}`}>{r.name}</Link>
                          <ProjectScopeLabel row={r} />
                        </td>
                        <td>
                          <div className="row" style={{ gap: "var(--space-2)" }}>
                            <FilterBadge
                              active={statusFilter === r.status}
                              tone={REQUIREMENT_STATUS_TONE[r.status]}
                              onClick={() => toggleStatusFilter(r.status)}
                            >
                              {REQUIREMENT_STATUS_LABEL[r.status]}
                            </FilterBadge>
                            {r.is_completed && <Badge>{strings.requirements.completedBadge}</Badge>}
                            {r.is_locked && <Badge>{strings.requirements.locked}</Badge>}
                            {r.is_archived && <Badge>{strings.requirements.archivedBadge}</Badge>}
                            {badges(r)}
                          </div>
                        </td>
                        <td className="text-muted">
                          {r.from_project_id ? "—" : stageName(r.target_stage_id)} · {REQUIREMENT_LEVEL_LABEL[r.level]}
                        </td>
                        <td className="text-muted">
                          {r.from_project_id ? "—" : `${componentName(r.component_id)} · ${categoryName(r.category_id)}`}
                        </td>
                        <td>
                          {!r.from_project_id && (
                            <div className="row" style={{ gap: "var(--space-1)" }}>
                              <button className="btn" onClick={() => move(r.id, "up")} title={strings.common.up} aria-label={strings.common.up}>
                                <ArrowUp />
                              </button>
                              <button className="btn" onClick={() => move(r.id, "down")} title={strings.common.down} aria-label={strings.common.down}>
                                <ArrowDown />
                              </button>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {requirements && (
              <LoadMoreButton
                loaded={requirements.length}
                total={total}
                onClick={() => loadRequirements(requirements.length, true)}
              />
            )}
          </div>
      </ListPageLayout>
    </div>
  );
}
