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
 * A `ViewToggle` switches between
 * this tree (the authoring/reordering view, hierarchy
 * intact) and a flat list view for scanning/searching a large
 * standard, with a `FilterPanel` (search text, mandatory-only, action
 * type) that applies to the list view only — filtering the flat list
 * before the tree is built would silently hide a matching child whose
 * ancestor didn't match, so the tree itself stays deliberately unfiltered,
 * matching the "the tree is for authoring, the list is for
 * scanning" framing. Clicking a list-view row opens a `SidePanel` detail
 * view (`RequirementDetailPanel` below) with `AutoGrowTextarea` fields for
 * description/reasoning, the same component `RequirementsPage.tsx`'s own
 * detail editing already uses, editable only while `isDraft`.
 *
 * A "Clarify" action (tree and list/detail view alike) is
 * shown once `isPublished` is true (mutually exclusive with `isDraft`'s own
 * edit/delete/move controls — a requirement is either freely editable, on
 * a draft version, or only clarifiable, on a published one; never both) —
 * opens `RequirementClarifyModal`, a mandatory-note-gated sibling of the
 * ordinary edit form. A clarified requirement shows a small `.badge` next
 * to its name (tree, list, and detail panel) with the clarification count
 * and, on hover/click, its most recent clarification note.
 */
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight, Link2, MessageSquareText, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { toErrorMessage, useToast } from "../../context/ToastContext";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { Modal } from "../../components/Modal";
import { SidePanel } from "../../components/SidePanel";
import { Spinner } from "../../components/Spinner";
import { useViewMode, ViewToggle } from "../../components/ViewToggle";
import * as complianceApi from "./api";
import { RequirementMappingsModal } from "./RequirementMappingsModal";
import type { ComplianceActionType, ComplianceRequiredAction, ComplianceRequirement, ComplianceRequirementNode } from "./types";
import { Badge } from "../../components/Badge";
import { CheckboxField, TextAreaField, TextField } from "../../components/FormFields";
import { FormActions } from "../../components/FormActions";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { RecordFieldGroup } from "../../components/RecordDetailParts";

interface Props {
  orgId: string;
  standardId: string;
  versionId: string;
  isDraft: boolean;
  /** Whether the owning version is `published` (as opposed to
   * `draft` or `retired`), the one status the "Clarify" action is offered
   * on (mirrors `clarify_requirement`'s own backend 409 on any other
   * status). */
  isPublished: boolean;
  actionTypes: ComplianceActionType[];
}

/** A small `.badge` marking a requirement clarified at least once —
 * shown in the tree, list, and detail views alike. The note is
 * surfaced via the native `title` tooltip on hover/click, mirroring how
 * this codebase already surfaces secondary detail without a second
 * control (e.g. this same file's own `title="View mappings"` buttons). */
function ClarificationBadge({ requirement }: { requirement: ComplianceRequirement }) {
  if (requirement.clarification_count === 0) return null;
  const times = requirement.clarification_count === 1 ? "1 time" : `${requirement.clarification_count} times`;
  return (
    <Badge
      icon={<MessageSquareText size={12} />}
      title={`Clarified ${times}. Most recent note: ${requirement.last_clarification_note || "(no note)"}`}>
      Clarified
    </Badge>
  );
}

export function RequirementTree({ orgId, standardId, versionId, isDraft, isPublished, actionTypes }: Props) {
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
  const [clarifyingRequirement, setClarifyingRequirement] = useState<ComplianceRequirement | null>(null);
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

  async function handleClarify(values: { reference: string; name: string; description: string; reasoning: string; clarificationNote: string }) {
    if (!clarifyingRequirement) return;
    try {
      await complianceApi.clarifyRequirement(orgId, standardId, versionId, clarifyingRequirement.id, {
        reference: values.reference || null,
        name: values.name,
        description: values.description,
        reasoning: values.reasoning,
        clarification_note: values.clarificationNote,
      });
      showToast("Requirement clarified.");
      setClarifyingRequirement(null);
      await reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not clarify requirement."), "error");
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
              {isExpanded ? <ChevronDown /> : <ChevronRight />}
            </button>
            <div className="stack" style={{ gap: "0.1rem", flex: 1, marginLeft: "0.5rem" }}>
              <strong className="row" style={{ gap: "0.4rem" }}>
                {node.reference && <span className="text-muted">{node.reference} — </span>}
                {node.name}
                <ClarificationBadge requirement={node} />
              </strong>
              {node.description && <span className="text-muted" style={{ fontSize: "0.85rem" }}>{node.description}</span>}
            </div>
            <div className="row">
              <button className="btn" title="View mappings" aria-label={`View mappings for ${node.name}`} onClick={() => setMappingsRequirement(node)}>
                <Link2 />
              </button>
              {isPublished && (
                <button className="btn" title="Clarify" aria-label={`Clarify ${node.name}`} onClick={() => setClarifyingRequirement(node)}>
                  <MessageSquareText />
                </button>
              )}
              {isDraft && (
                <>
                  <button
                    className="btn"
                    title="Add child requirement"
                    aria-label={`Add child requirement under ${node.name}`}
                    onClick={() => setEditingRequirement({ parentId: node.id })}
                  >
                    <Plus />
                  </button>
                  <button className="btn" title="Edit" aria-label={`Edit ${node.name}`} onClick={() => setEditingRequirement({ parentId: node.parent_requirement_id, requirement: node })}>
                    <Pencil />
                  </button>
                  <button className="btn" disabled={index === 0} title="Move up" aria-label={`Move ${node.name} up`} onClick={() => handleMoveRequirement(node.id, "up")}>
                    <ArrowUp />
                  </button>
                  <button
                    className="btn"
                    disabled={index === siblings.length - 1}
                    title="Move down"
                    aria-label={`Move ${node.name} down`}
                    onClick={() => handleMoveRequirement(node.id, "down")}
                  >
                    <ArrowDown />
                  </button>
                  <button className="btn btn-danger" title="Delete" aria-label={`Delete ${node.name}`} onClick={() => setDeletingRequirement(node)}>
                    <Trash2 />
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
                            <Pencil />
                          </button>
                          <button
                            className="btn"
                            disabled={actionIndex === 0}
                            title="Move up"
                            aria-label={`Move required action ${action.name} up`}
                            onClick={() => handleMoveAction(node.id, action.id, "up")}
                          >
                            <ArrowUp />
                          </button>
                          <button
                            className="btn"
                            disabled={actionIndex === actions.length - 1}
                            title="Move down"
                            aria-label={`Move required action ${action.name} down`}
                            onClick={() => handleMoveAction(node.id, action.id, "down")}
                          >
                            <ArrowDown />
                          </button>
                          <button
                            className="btn btn-danger"
                            title="Delete"
                            aria-label={`Delete required action ${action.name}`}
                            onClick={() => setDeletingAction({ requirementId: node.id, action })}
                          >
                            <Trash2 />
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
                  <Plus /> Add required action
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
            <Plus /> Add requirement
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
                        <strong className="row" style={{ gap: "0.4rem" }}>
                          {req.reference && <span className="text-muted">{req.reference} — </span>}
                          {req.name}
                          <ClarificationBadge requirement={req} />
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
          isPublished={isPublished}
          onClarify={() => {
            setClarifyingRequirement(detailRequirement);
            setDetailRequirement(null);
          }}
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
      {clarifyingRequirement && (
        <RequirementClarifyModal
          requirement={clarifyingRequirement}
          onCancel={() => setClarifyingRequirement(null)}
          onSave={handleClarify}
        />
      )}
    </div>
  );
}

/**
 * The list view's "open full detail" panel — a `SidePanel`
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
  isPublished,
  onClarify,
  onClose,
  onSave,
}: {
  requirement: ComplianceRequirement;
  actions: ComplianceRequiredAction[] | undefined;
  actionTypes: ComplianceActionType[];
  isDraft: boolean;
  isPublished: boolean;
  onClarify: () => void;
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
        <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
          <ClarificationBadge requirement={requirement} />
          {isPublished && (
            <button className="btn" onClick={onClarify}>
              <MessageSquareText /> Clarify
            </button>
          )}
        </div>
        {isDraft ? (
          <FormGrid minColumn="14rem">
            <TextField label="Reference" value={reference} onChange={setReference} placeholder="e.g. A.5.1" />
            <TextField label="Name" ariaLabel="Requirement name" value={name} onChange={setName} />
            <FormGridFull>
              <TextAreaField label="Description" value={description} onChange={setDescription} autoGrow />
            </FormGridFull>
            <FormGridFull>
              <TextAreaField label="Reasoning" value={reasoning} onChange={setReasoning} autoGrow />
            </FormGridFull>
          </FormGrid>
        ) : (
          <>
            <RecordFieldGroup label="Reference">
              <span>{requirement.reference || <span className="text-muted">None</span>}</span>
            </RecordFieldGroup>
            <RecordFieldGroup label="Name"><span>{requirement.name}</span></RecordFieldGroup>
            <RecordFieldGroup label="Description">
              <span>{requirement.description || <span className="text-muted">No description.</span>}</span>
            </RecordFieldGroup>
            <RecordFieldGroup label="Reasoning">
              <span>{requirement.reasoning || <span className="text-muted">No reasoning recorded.</span>}</span>
            </RecordFieldGroup>
          </>
        )}

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
    <Modal title={initial ? "Edit requirement" : "New requirement"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <TextField label="Reference" value={reference} onChange={setReference} placeholder="e.g. A.5.1" />
          <TextField label="Name" ariaLabel="Requirement name" value={name} onChange={setName} />
          <FormGridFull>
            <TextAreaField label="Description" value={description} onChange={setDescription} rows={3} />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField label="Reasoning" value={reasoning} onChange={setReasoning} rows={2} />
          </FormGridFull>
        </FormGrid>
        <FormActions
          onCancel={onCancel}
          onSave={() => onSave({ reference, name, description, reasoning })}
          saveDisabled={!name.trim()}
        />
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
  // The types may arrive after this form opens (the page loads them in
  // parallel); adopt the first one then, or Save stays disabled for good
  // (found 2026-10-04 via the e2e suite under load). React's "adjust state
  // during render" pattern — converges in one extra render.
  if (actionTypeId === "" && actionTypes[0]) setActionTypeId(actionTypes[0].id);
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [isMandatory, setIsMandatory] = useState(initial?.is_mandatory ?? true);

  return (
    <Modal title={initial ? "Edit required action" : "New required action"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <LabeledSelect
            label="Action type"
            value={actionTypeId}
            onChange={setActionTypeId}
            options={actionTypes.map((t) => ({ value: t.id, label: t.name }))}
            placeholder={null}
          />
          <TextField label="Name" ariaLabel="Required action name" value={name} onChange={setName} />
          <FormGridFull>
            <TextAreaField label="Description" value={description} onChange={setDescription} rows={2} />
          </FormGridFull>
          <CheckboxField label="Mandatory" checked={isMandatory} onChange={setIsMandatory} />
        </FormGrid>
        <FormActions
          onCancel={onCancel}
          onSave={() => onSave({ action_type_id: actionTypeId, name, description, is_mandatory: isMandatory })}
          saveDisabled={!name.trim() || !actionTypeId}
        />
      </div>
    </Modal>
  );
}

/**
 * The "Clarify" action — a narrower, mandatory-note-gated sibling of
 * `RequirementFormModal`, for a requirement on a **published** version.
 * Pre-fills the same reference/name/description/reasoning fields (a
 * clarification is a correction/elaboration to this requirement's own
 * wording, not a different action), but requires `clarificationNote`
 * before Save enables — the backend 400s without one for the same reason
 * (see `router.py::clarify_requirement`'s own docstring: there is no
 * reliable way to detect "non-substantive" from the fields alone, so the
 * note is what makes the distinction accountable).
 */
function RequirementClarifyModal({
  requirement,
  onCancel,
  onSave,
}: {
  requirement: ComplianceRequirement;
  onCancel: () => void;
  onSave: (values: { reference: string; name: string; description: string; reasoning: string; clarificationNote: string }) => void;
}) {
  const [reference, setReference] = useState(requirement.reference ?? "");
  const [name, setName] = useState(requirement.name);
  const [description, setDescription] = useState(requirement.description);
  const [reasoning, setReasoning] = useState(requirement.reasoning);
  const [clarificationNote, setClarificationNote] = useState("");

  return (
    <Modal title={`Clarify "${requirement.name}"`} onClose={onCancel} size="lg">
      <div className="stack">
        <p className="text-muted" style={{ margin: 0 }}>
          Use this for a non-substantive correction or elaboration only — a typo fix, added context, or formatting.
          Anything that changes what must be satisfied requires a new standard version instead.
        </p>
        <FormGrid minColumn="18rem">
          <TextField label="Reference" value={reference} onChange={setReference} placeholder="e.g. A.5.1" />
          <TextField label="Name" ariaLabel="Requirement name" value={name} onChange={setName} />
          <FormGridFull>
            <TextAreaField label="Description" value={description} onChange={setDescription} autoGrow />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField label="Reasoning" value={reasoning} onChange={setReasoning} autoGrow />
          </FormGridFull>
          <FormGridFull>
            <TextAreaField
              label="Clarification note (required)" value={clarificationNote} onChange={setClarificationNote} autoGrow
              inputProps={{ placeholder: "What changed, and why it's non-substantive." }}
            />
          </FormGridFull>
        </FormGrid>
        <FormActions
          onCancel={onCancel}
          onSave={() => onSave({ reference, name, description, reasoning, clarificationNote })}
          saveLabel="Save clarification"
          saveDisabled={!name.trim() || !clarificationNote.trim()}
        />
      </div>
    </Modal>
  );
}
