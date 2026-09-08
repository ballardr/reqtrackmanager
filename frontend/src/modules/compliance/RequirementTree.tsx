/**
 * Module: modules/compliance/RequirementTree
 *
 * The requirement-hierarchy editor for one `ComplianceStandardVersion` (§5)
 * — a client-side-assembled tree (see `api.ts::buildRequirementTree`) over
 * the backend's flat, depth-first-ordered `GET .../requirements` list, with
 * each requirement's required actions (§6) nested underneath, lazily
 * fetched on first expand.
 *
 * Mutations (add/edit/delete/move a requirement or required action) are
 * disabled whenever `isDraft` is false — mirrors the backend's own
 * "published version's requirements become immutable" rule (§4,
 * `router.py::_require_draft_version`) so a 409 from a stale client state
 * is the exception, not the everyday path; the UI simply doesn't offer the
 * controls once a version stops being a draft, rather than letting a click
 * round-trip into an error toast.
 *
 * Follows this repo's established tree-editor shape (`ProjectTree.tsx`):
 * presentational recursion, expand/collapse via local component state
 * (`expandedIds`), no shared "generic tree" component extracted — a
 * requirement/required-action tree with per-node CRUD + mappings is
 * specific enough to this module that following `ProjectTree`'s pattern
 * (not its component) is the right level of reuse, matching how
 * `ProjectTree` itself is not shared beyond project hierarchy either.
 *
 * Phase 23 (Standard workspace UX overhaul) adds a `ViewToggle` between
 * this tree (unchanged — still the authoring/reordering view, hierarchy
 * intact) and a new flat list view for scanning/searching a large
 * standard, with a `FilterPanel` (search text, mandatory-only, action
 * type) that applies to the list view only — filtering the flat list
 * before the tree is built would silently hide a matching child whose
 * ancestor didn't match, so the tree itself stays deliberately unfiltered,
 * matching this phase's own "the tree is for authoring, the list is for
 * scanning" framing. Clicking a list-view row opens a `SidePanel` detail
 * view (`RequirementDetailPanel` below) with `AutoGrowTextarea` fields for
 * description/reasoning, the same component `RequirementsPage.tsx`'s own
 * detail editing already uses, editable only while `isDraft`.
 */
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Link2, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { toErrorMessage, useToast } from "../../context/ToastContext";
import { AutoGrowTextarea } from "../../components/AutoGrowTextarea";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { Modal } from "../../components/Modal";
import { SidePanel } from "../../components/SidePanel";
import { Spinner } from "../../components/Spinner";
import { useViewMode, ViewToggle } from "../../components/ViewToggle";
import * as complianceApi from "./api";
import { RequirementMappingsModal } from "./RequirementMappingsModal";
import type { ComplianceActionType, ComplianceRequiredAction, ComplianceRequirement, ComplianceRequirementNode } from "./types";

interface Props {
  orgId: string;
  standardId: string;
  versionId: string;
  isDraft: boolean;
  actionTypes: ComplianceActionType[];
}

export function RequirementTree({ orgId, standardId, versionId, isDraft, actionTypes }: Props) {
  const { showToast } = useToast();
  const [requirements, setRequirements] = useState<ComplianceRequirement[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [actionsByRequirement, setActionsByRequirement] = useState<Record<string, ComplianceRequiredAction[]>>({});
  const [viewMode, setViewMode] = useViewMode("complianceRequirementTree", "tree");
  const [search, setSearch] = useState("");
  const [mandatoryOnly, setMandatoryOnly] = useState(false);
  const [actionTypeFilter, setActionTypeFilter] = useState("");
  const [detailRequirement, setDetailRequirement] = useState<ComplianceRequirement | null>(null);

  const [editingRequirement, setEditingRequirement] = useState<{ parentId: string | null; requirement?: ComplianceRequirement } | null>(null);
  const [deletingRequirement, setDeletingRequirement] = useState<ComplianceRequirement | null>(null);
  const [mappingsRequirement, setMappingsRequirement] = useState<ComplianceRequirement | null>(null);
  const [editingAction, setEditingAction] = useState<{ requirementId: string; action?: ComplianceRequiredAction } | null>(null);
  const [deletingAction, setDeletingAction] = useState<{ requirementId: string; action: ComplianceRequiredAction } | null>(null);

  async function reload() {
    try {
      setRequirements(await complianceApi.listRequirements(orgId, standardId, versionId));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Could not load requirements."));
    }
  }

  useEffect(() => {
    setRequirements(null);
    setExpandedIds(new Set());
    setActionsByRequirement({});
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId, standardId, versionId]);

  async function toggleExpand(requirementId: string) {
    const next = new Set(expandedIds);
    if (next.has(requirementId)) {
      next.delete(requirementId);
      setExpandedIds(next);
      return;
    }
    next.add(requirementId);
    setExpandedIds(next);
    if (!actionsByRequirement[requirementId]) {
      try {
        const actions = await complianceApi.listRequiredActions(orgId, standardId, versionId, requirementId);
        setActionsByRequirement((prev) => ({ ...prev, [requirementId]: actions }));
      } catch (err) {
        showToast(toErrorMessage(err, "Could not load required actions."), "error");
      }
    }
  }

  async function handleSaveRequirement(values: { reference: string; name: string; description: string; reasoning: string }) {
    try {
      if (editingRequirement?.requirement) {
        await complianceApi.updateRequirement(orgId, standardId, versionId, editingRequirement.requirement.id, {
          reference: values.reference || null,
          name: values.name,
          description: values.description,
          reasoning: values.reasoning,
        });
        showToast("Requirement updated.");
      } else {
        await complianceApi.createRequirement(orgId, standardId, versionId, {
          parent_requirement_id: editingRequirement?.parentId ?? null,
          reference: values.reference || null,
          name: values.name,
          description: values.description,
          reasoning: values.reasoning,
        });
        showToast("Requirement created.");
      }
      setEditingRequirement(null);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not save requirement."), "error");
    }
  }

  async function handleDeleteRequirement() {
    if (!deletingRequirement) return;
    try {
      await complianceApi.deleteRequirement(orgId, standardId, versionId, deletingRequirement.id);
      showToast("Requirement deleted.");
      setDeletingRequirement(null);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not delete requirement."), "error");
    }
  }

  async function handleMoveRequirement(requirementId: string, direction: "up" | "down") {
    try {
      await complianceApi.moveRequirement(orgId, standardId, versionId, requirementId, direction);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not reorder requirement."), "error");
    }
  }

  async function handleSaveAction(values: { action_type_id: string; name: string; description: string; is_mandatory: boolean }) {
    if (!editingAction) return;
    try {
      if (editingAction.action) {
        await complianceApi.updateRequiredAction(orgId, standardId, versionId, editingAction.requirementId, editingAction.action.id, values);
        showToast("Required action updated.");
      } else {
        await complianceApi.createRequiredAction(orgId, standardId, versionId, editingAction.requirementId, values);
        showToast("Required action created.");
      }
      const requirementId = editingAction.requirementId;
      setEditingAction(null);
      const actions = await complianceApi.listRequiredActions(orgId, standardId, versionId, requirementId);
      setActionsByRequirement((prev) => ({ ...prev, [requirementId]: actions }));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not save required action."), "error");
    }
  }

  async function handleDeleteAction() {
    if (!deletingAction) return;
    try {
      await complianceApi.deleteRequiredAction(orgId, standardId, versionId, deletingAction.requirementId, deletingAction.action.id);
      showToast("Required action deleted.");
      const requirementId = deletingAction.requirementId;
      setDeletingAction(null);
      const actions = await complianceApi.listRequiredActions(orgId, standardId, versionId, requirementId);
      setActionsByRequirement((prev) => ({ ...prev, [requirementId]: actions }));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not delete required action."), "error");
    }
  }

  async function handleMoveAction(requirementId: string, actionId: string, direction: "up" | "down") {
    try {
      await complianceApi.moveRequiredAction(orgId, standardId, versionId, requirementId, actionId, direction);
      const actions = await complianceApi.listRequiredActions(orgId, standardId, versionId, requirementId);
      setActionsByRequirement((prev) => ({ ...prev, [requirementId]: actions }));
    } catch (err) {
      showToast(toErrorMessage(err, "Could not reorder required action."), "error");
    }
  }

  // List view's search/mandatory/action-type filters all need every
  // requirement's required actions loaded, not just the (lazily-expanded)
  // ones the tree view has fetched so far — fetch whatever's missing once
  // the list view is active, rather than a new "all actions for this
  // version" backend endpoint the tree view has never needed.
  useEffect(() => {
    if (viewMode !== "list" || !requirements) return;
    const missing = requirements.filter((r) => !actionsByRequirement[r.id]);
    if (missing.length === 0) return;
    void Promise.all(
      missing.map((r) =>
        complianceApi
          .listRequiredActions(orgId, standardId, versionId, r.id)
          .then((actions) => [r.id, actions] as const)
      )
    ).then((entries) => {
      setActionsByRequirement((prev) => {
        const next = { ...prev };
        for (const [id, actions] of entries) next[id] = actions;
        return next;
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewMode, requirements]);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (requirements === null) return <Spinner />;

  const tree = complianceApi.buildRequirementTree(requirements);

  const searchLower = search.trim().toLowerCase();
  const filteredRequirements = requirements.filter((r) => {
    if (searchLower) {
      const haystack = `${r.reference ?? ""} ${r.name} ${r.description}`.toLowerCase();
      if (!haystack.includes(searchLower)) return false;
    }
    const actions = actionsByRequirement[r.id];
    if (mandatoryOnly && !actions?.some((a) => a.is_mandatory)) return false;
    if (actionTypeFilter && !actions?.some((a) => a.action_type_id === actionTypeFilter)) return false;
    return true;
  });

  function renderNode(node: ComplianceRequirementNode, siblings: ComplianceRequirementNode[], index: number) {
    const isExpanded = expandedIds.has(node.id);
    const actions = actionsByRequirement[node.id];
    return (
      <li key={node.id} style={{ marginLeft: node.depth === 0 ? 0 : "1.25rem" }}>
        <div className="card stack" style={{ padding: "0.5rem 0.75rem", marginBottom: "0.4rem" }}>
          <div className="row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
            <button
              type="button"
              className="btn"
              aria-label={isExpanded ? `Collapse ${node.name}` : `Expand ${node.name}`}
              onClick={() => toggleExpand(node.id)}
            >
              {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            </button>
            <div className="stack" style={{ gap: "0.1rem", flex: 1, marginLeft: "0.5rem" }}>
              <strong>
                {node.reference && <span className="text-muted">{node.reference} — </span>}
                {node.name}
              </strong>
              {node.description && <span className="text-muted" style={{ fontSize: "0.85rem" }}>{node.description}</span>}
            </div>
            <div className="row">
              <button className="btn" title="View mappings" aria-label={`View mappings for ${node.name}`} onClick={() => setMappingsRequirement(node)}>
                <Link2 size={14} />
              </button>
              {isDraft && (
                <>
                  <button
                    className="btn"
                    title="Add child requirement"
                    aria-label={`Add child requirement under ${node.name}`}
                    onClick={() => setEditingRequirement({ parentId: node.id })}
                  >
                    <Plus size={14} />
                  </button>
                  <button className="btn" title="Edit" aria-label={`Edit ${node.name}`} onClick={() => setEditingRequirement({ parentId: node.parent_requirement_id, requirement: node })}>
                    <Pencil size={14} />
                  </button>
                  <button className="btn" disabled={index === 0} title="Move up" aria-label={`Move ${node.name} up`} onClick={() => handleMoveRequirement(node.id, "up")}>
                    <ArrowUp size={14} />
                  </button>
                  <button
                    className="btn"
                    disabled={index === siblings.length - 1}
                    title="Move down"
                    aria-label={`Move ${node.name} down`}
                    onClick={() => handleMoveRequirement(node.id, "down")}
                  >
                    <ArrowDown size={14} />
                  </button>
                  <button className="btn btn-danger" title="Delete" aria-label={`Delete ${node.name}`} onClick={() => setDeletingRequirement(node)}>
                    <Trash2 size={14} />
                  </button>
                </>
              )}
            </div>
          </div>
          {isExpanded && (
            <div className="stack" style={{ marginLeft: "1.75rem", borderLeft: "2px solid var(--color-border)", paddingLeft: "0.75rem" }}>
              <h4 style={{ margin: "0.25rem 0 0" }}>Required actions</h4>
              {actions === undefined ? (
                <Spinner />
              ) : actions.length === 0 ? (
                <p className="text-muted" style={{ margin: 0 }}>No required actions yet.</p>
              ) : (
                <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                  {actions.map((action, actionIndex) => (
                    <li key={action.id} className="row" style={{ justifyContent: "space-between", padding: "0.25rem 0" }}>
                      <span>
                        {action.name}
                        {action.is_mandatory && <span className="text-muted"> (mandatory)</span>}
                        <span className="text-muted"> — {actionTypes.find((t) => t.id === action.action_type_id)?.name ?? "—"}</span>
                      </span>
                      {isDraft && (
                        <div className="row">
                          <button className="btn" title="Edit" aria-label={`Edit required action ${action.name}`} onClick={() => setEditingAction({ requirementId: node.id, action })}>
                            <Pencil size={14} />
                          </button>
                          <button
                            className="btn"
                            disabled={actionIndex === 0}
                            title="Move up"
                            aria-label={`Move required action ${action.name} up`}
                            onClick={() => handleMoveAction(node.id, action.id, "up")}
                          >
                            <ArrowUp size={14} />
                          </button>
                          <button
                            className="btn"
                            disabled={actionIndex === actions.length - 1}
                            title="Move down"
                            aria-label={`Move required action ${action.name} down`}
                            onClick={() => handleMoveAction(node.id, action.id, "down")}
                          >
                            <ArrowDown size={14} />
                          </button>
                          <button
                            className="btn btn-danger"
                            title="Delete"
                            aria-label={`Delete required action ${action.name}`}
                            onClick={() => setDeletingAction({ requirementId: node.id, action })}
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {isDraft && (
                <button
                  className="btn"
                  style={{ alignSelf: "flex-start" }}
                  disabled={actionTypes.length === 0}
                  title={actionTypes.length === 0 ? "Create an action type first" : undefined}
                  onClick={() => setEditingAction({ requirementId: node.id })}
                >
                  <Plus size={14} /> Add required action
                </button>
              )}
            </div>
          )}
        </div>
        {node.children.length > 0 && (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {node.children.map((child, childIndex) => renderNode(child, node.children, childIndex))}
          </ul>
        )}
      </li>
    );
  }

  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
        {isDraft ? (
          <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setEditingRequirement({ parentId: null })}>
            <Plus size={14} /> Add requirement
          </button>
        ) : (
          <span />
        )}
        <ViewToggle mode={viewMode} onChange={setViewMode} showTilesOption={false} showTreeOption />
      </div>

      {viewMode === "tree" ? (
        tree.length === 0 ? (
          <p className="text-muted">No requirements defined for this version yet.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>{tree.map((node, index) => renderNode(node, tree, index))}</ul>
        )
      ) : (
        <div className="side-grid">
          <div className="stack">
            {filteredRequirements.length === 0 ? (
              <p className="text-muted">No requirements match these filters.</p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {filteredRequirements.map((req) => (
                  <li key={req.id} style={{ borderBottom: "1px solid var(--color-border)" }}>
                    <button
                      type="button"
                      className="btn"
                      style={{ width: "100%", justifyContent: "flex-start", textAlign: "left", padding: "0.6rem 0.5rem" }}
                      onClick={() => setDetailRequirement(req)}
                    >
                      <span className="stack" style={{ gap: "0.1rem" }}>
                        <strong>
                          {req.reference && <span className="text-muted">{req.reference} — </span>}
                          {req.name}
                        </strong>
                        {req.description && <span className="text-muted" style={{ fontSize: "0.85rem" }}>{req.description}</span>}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <FilterPanel
            sectionKey="complianceRequirementTree"
            matching={filteredRequirements.length}
            total={requirements.length}
            search={search}
            onSearchChange={setSearch}
            searchPlaceholder="Search requirements…"
          >
            <FilterCheckbox label="Mandatory action only" checked={mandatoryOnly} onChange={setMandatoryOnly} />
            <FilterField label="Action type">
              <select className="input" value={actionTypeFilter} onChange={(e) => setActionTypeFilter(e.target.value)}>
                <option value="">All action types</option>
                {actionTypes.map((t) => (
                  <option key={t.id} value={t.id}>{t.name}</option>
                ))}
              </select>
            </FilterField>
          </FilterPanel>
        </div>
      )}

      {detailRequirement && (
        <RequirementDetailPanel
          requirement={detailRequirement}
          actions={actionsByRequirement[detailRequirement.id]}
          actionTypes={actionTypes}
          isDraft={isDraft}
          onClose={() => setDetailRequirement(null)}
          onSave={async (values) => {
            try {
              await complianceApi.updateRequirement(orgId, standardId, versionId, detailRequirement.id, {
                reference: values.reference || null,
                name: values.name,
                description: values.description,
                reasoning: values.reasoning,
              });
              showToast("Requirement updated.");
              const updated = await complianceApi.listRequirements(orgId, standardId, versionId);
              setRequirements(updated);
              // Functional update, not a blind overwrite: if the panel was
              // already closed (or switched to a different requirement)
              // while this save's own round trip was still in flight, this
              // must not reopen it — a real race a fast Save-then-Close
              // hit in practice.
              setDetailRequirement((current) =>
                current?.id === detailRequirement.id ? updated.find((r) => r.id === detailRequirement.id) ?? null : current
              );
            } catch (err) {
              showToast(toErrorMessage(err, "Could not save requirement."), "error");
            }
          }}
        />
      )}

      {editingRequirement && (
        <RequirementFormModal
          initial={editingRequirement.requirement}
          onCancel={() => setEditingRequirement(null)}
          onSave={handleSaveRequirement}
        />
      )}
      {deletingRequirement && (
        <ConfirmDialog
          title={`Delete "${deletingRequirement.name}"?`}
          message="This also deletes every child requirement and required action underneath it. This cannot be undone."
          confirmLabel="Delete"
          onConfirm={handleDeleteRequirement}
          onCancel={() => setDeletingRequirement(null)}
        />
      )}
      {mappingsRequirement && (
        <RequirementMappingsModal
          orgId={orgId}
          standardId={standardId}
          versionId={versionId}
          requirement={mappingsRequirement}
          onClose={() => setMappingsRequirement(null)}
        />
      )}
      {editingAction && (
        <RequiredActionFormModal
          initial={editingAction.action}
          actionTypes={actionTypes}
          onCancel={() => setEditingAction(null)}
          onSave={handleSaveAction}
        />
      )}
      {deletingAction && (
        <ConfirmDialog
          title={`Delete required action "${deletingAction.action.name}"?`}
          message="This cannot be undone."
          confirmLabel="Delete"
          onConfirm={handleDeleteAction}
          onCancel={() => setDeletingAction(null)}
        />
      )}
    </div>
  );
}

/**
 * The list view's "open full detail" panel (Phase 23) — a `SidePanel`
 * reusing `AutoGrowTextarea` for description/reasoning, the same field
 * component `RequirementsPage.tsx`'s own detail editing already uses.
 * Reference/name/description/reasoning are editable while `isDraft`
 * (mirrors `RequirementFormModal`'s own draft-only editability); required
 * actions are shown read-only here — the tree view's existing expand-row
 * add/edit/delete/move controls remain the one place that manages them,
 * rather than this panel duplicating that whole CRUD surface a second
 * time.
 */
function RequirementDetailPanel({
  requirement,
  actions,
  actionTypes,
  isDraft,
  onClose,
  onSave,
}: {
  requirement: ComplianceRequirement;
  actions: ComplianceRequiredAction[] | undefined;
  actionTypes: ComplianceActionType[];
  isDraft: boolean;
  onClose: () => void;
  onSave: (values: { reference: string; name: string; description: string; reasoning: string }) => void;
}) {
  const [reference, setReference] = useState(requirement.reference ?? "");
  const [name, setName] = useState(requirement.name);
  const [description, setDescription] = useState(requirement.description);
  const [reasoning, setReasoning] = useState(requirement.reasoning);

  const dirty =
    reference !== (requirement.reference ?? "") || name !== requirement.name ||
    description !== requirement.description || reasoning !== requirement.reasoning;

  return (
    <SidePanel title={requirement.name} onClose={onClose}>
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Reference</span>
          {isDraft ? (
            <input className="input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="e.g. A.5.1" />
          ) : (
            <span>{requirement.reference || <span className="text-muted">None</span>}</span>
          )}
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Name</span>
          {isDraft ? (
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} aria-label="Requirement name" />
          ) : (
            <span>{requirement.name}</span>
          )}
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Description</span>
          {isDraft ? (
            <AutoGrowTextarea value={description} onChange={setDescription} />
          ) : (
            <span>{requirement.description || <span className="text-muted">No description.</span>}</span>
          )}
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Reasoning</span>
          {isDraft ? (
            <AutoGrowTextarea value={reasoning} onChange={setReasoning} />
          ) : (
            <span>{requirement.reasoning || <span className="text-muted">No reasoning recorded.</span>}</span>
          )}
        </label>

        {isDraft && (
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button
              className="btn btn-primary"
              disabled={!dirty || !name.trim()}
              onClick={() => onSave({ reference, name, description, reasoning })}
            >
              Save
            </button>
          </div>
        )}

        <h4 style={{ margin: "0.5rem 0 0" }}>Required actions</h4>
        {actions === undefined ? (
          <Spinner />
        ) : actions.length === 0 ? (
          <p className="text-muted" style={{ margin: 0 }}>No required actions yet.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {actions.map((action) => (
              <li key={action.id} style={{ padding: "0.25rem 0" }}>
                {action.name}
                {action.is_mandatory && <span className="text-muted"> (mandatory)</span>}
                <span className="text-muted"> — {actionTypes.find((t) => t.id === action.action_type_id)?.name ?? "—"}</span>
              </li>
            ))}
          </ul>
        )}
        {isDraft && (
          <p className="text-muted" style={{ margin: 0, fontSize: "0.85rem" }}>
            Switch to tree view to add, edit, or reorder required actions.
          </p>
        )}
      </div>
    </SidePanel>
  );
}

function RequirementFormModal({
  initial,
  onCancel,
  onSave,
}: {
  initial?: ComplianceRequirement;
  onCancel: () => void;
  onSave: (values: { reference: string; name: string; description: string; reasoning: string }) => void;
}) {
  const [reference, setReference] = useState(initial?.reference ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [reasoning, setReasoning] = useState(initial?.reasoning ?? "");

  return (
    <Modal title={initial ? "Edit requirement" : "New requirement"} onClose={onCancel}>
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Reference</span>
          <input className="input" value={reference} onChange={(e) => setReference(e.target.value)} placeholder="e.g. A.5.1" />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Name</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} aria-label="Requirement name" />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Description</span>
          <textarea className="input" value={description} onChange={(e) => setDescription(e.target.value)} rows={3} />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Reasoning</span>
          <textarea className="input" value={reasoning} onChange={(e) => setReasoning(e.target.value)} rows={2} />
        </label>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={!name.trim()}
            onClick={() => onSave({ reference, name, description, reasoning })}
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}

function RequiredActionFormModal({
  initial,
  actionTypes,
  onCancel,
  onSave,
}: {
  initial?: ComplianceRequiredAction;
  actionTypes: ComplianceActionType[];
  onCancel: () => void;
  onSave: (values: { action_type_id: string; name: string; description: string; is_mandatory: boolean }) => void;
}) {
  const [actionTypeId, setActionTypeId] = useState(initial?.action_type_id ?? actionTypes[0]?.id ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [isMandatory, setIsMandatory] = useState(initial?.is_mandatory ?? true);

  return (
    <Modal title={initial ? "Edit required action" : "New required action"} onClose={onCancel}>
      <div className="stack">
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Action type</span>
          <select className="input" value={actionTypeId} onChange={(e) => setActionTypeId(e.target.value)} aria-label="Action type">
            {actionTypes.map((t) => (
              <option key={t.id} value={t.id}>{t.name}</option>
            ))}
          </select>
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Name</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} aria-label="Required action name" />
        </label>
        <label className="stack" style={{ gap: "0.25rem" }}>
          <span>Description</span>
          <textarea className="input" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} />
        </label>
        <label className="row" style={{ gap: "0.4rem" }}>
          <input type="checkbox" checked={isMandatory} onChange={(e) => setIsMandatory(e.target.checked)} />
          Mandatory
        </label>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn" onClick={onCancel}>Cancel</button>
          <button
            className="btn btn-primary"
            disabled={!name.trim() || !actionTypeId}
            onClick={() => onSave({ action_type_id: actionTypeId, name, description, is_mandatory: isMandatory })}
          >
            Save
          </button>
        </div>
      </div>
    </Modal>
  );
}
