/**
 * Module: modules/decisions/DecisionTemplatesPanel
 *
 * The org-scoped Decision Template library (Phase 0 addendum items 1/2/6/7)
 * — registered as this module's `orgAdminSections` contribution
 * (`module.ts`; moved here from `orgOverviewSections` in Phase 9,
 * 2026-09-22, per explicit user direction — an org admin manages this
 * library on Org Management, not the Org Dashboard), the org-level
 * counterpart to the opt-in template-pack picker
 * `pages/ServerOrganisationsPage.tsx` already surfaces at
 * organisation-creation time (`GET /orgs/creation-choices`). This panel is
 * where an org admin manages the template library *after* creation —
 * editing a seeded pack, adding a custom one, or removing one nobody wants.
 *
 * `DirectoryTable` + `Modal` create/edit (`DecisionTemplateFormModal`) +
 * `ConfirmDialog` delete — the same shape `EvidencePanel.tsx` uses for its
 * own CRUD list, minus a detail `SidePanel` (a template has no sub-resources
 * of its own worth drilling into; edit reopens the same form). Row actions
 * (Edit, Delete) are a per-row `ActionMenu` in an Actions column — never a
 * block of delete buttons collected below the table, and never an action
 * reachable only via row-click with no corresponding menu entry (style
 * guide's "Pattern: action menu" table addendum and "Pattern: directory
 * table" callout, both 2026-09-22 — this panel was the finding that
 * prompted both). The row itself stays clickable to open the edit form as a
 * shortcut; "Edit" is still listed in the menu too, since a shortcut is
 * never a substitute for a menu entry.
 */
import { useEffect, useState } from "react";
import { Pencil, Trash2 } from "lucide-react";

import { ActionMenu } from "../../components/ActionMenu";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import { DecisionTemplateFormModal } from "./DecisionTemplateFormModal";
import type { DecisionTemplate } from "./types";

export function DecisionTemplatesPanel({ orgId }: { orgId: string }) {
  const { showToast } = useToast();
  const [templates, setTemplates] = useState<DecisionTemplate[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<DecisionTemplate | null>(null);
  const [deleting, setDeleting] = useState<DecisionTemplate | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  async function reload() {
    try {
      setTemplates(await decisionsApi.listDecisionTemplates(orgId));
      setLoadError(null);
    } catch (err) {
      setLoadError(toErrorMessage(err, "Could not load Decision Templates."));
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (templates === null) return <Spinner />;

  const columns: DirectoryColumn<DecisionTemplate>[] = [
    { key: "name", label: "Name", render: (t) => t.name },
    { key: "description", label: "Description", render: (t) => t.description || "—" },
    {
      key: "actions", label: "",
      render: (t) => (
        <ActionMenu
          triggerLabel={`Actions for "${t.name}"`}
          items={[
            { label: "Edit", icon: <Pencil size={14} />, onSelect: () => setEditing(t) },
            { label: "Delete", icon: <Trash2 size={14} />, onSelect: () => setDeleting(t) },
          ]}
        />
      ),
    },
  ];

  return (
    <div className="stack">
      <p className="text-muted" style={{ margin: 0 }}>
        Templates pre-fill guidance text into a Decision's content fields when picked at creation time — a starting
        point, not a permanent link (editing or deleting a template never affects a Decision already created from it).
      </p>
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        New decision template
      </button>
      <DirectoryTable
        ariaLabel="Decision templates"
        columns={columns}
        rows={templates}
        rowKey={(t) => t.id}
        onRowClick={setEditing}
        emptyState={<p className="text-muted">No Decision Templates yet.</p>}
      />
      {creating && (
        <DecisionTemplateFormModal
          error={formError}
          onCancel={() => { setCreating(false); setFormError(null); }}
          onSave={async (values) => {
            setFormError(null);
            try {
              await decisionsApi.createDecisionTemplate(orgId, values);
              showToast("Decision template created.");
              setCreating(false);
              await reload();
            } catch (err) {
              setFormError(toErrorMessage(err, "Could not create decision template."));
            }
          }}
        />
      )}

      {editing && (
        <DecisionTemplateFormModal
          initial={editing}
          error={formError}
          onCancel={() => { setEditing(null); setFormError(null); }}
          onSave={async (values) => {
            setFormError(null);
            try {
              await decisionsApi.updateDecisionTemplate(orgId, editing.id, values);
              showToast("Decision template updated.");
              setEditing(null);
              await reload();
            } catch (err) {
              setFormError(toErrorMessage(err, "Could not update decision template."));
            }
          }}
        />
      )}

      {deleting && (
        <ConfirmDialog
          title={`Delete "${deleting.name}"?`}
          message="This template will no longer be offered when creating a Decision. Decisions already created from it are unaffected."
          confirmLabel="Delete"
          onConfirm={async () => {
            const target = deleting;
            setDeleting(null);
            try {
              await decisionsApi.deleteDecisionTemplate(orgId, target.id);
              showToast("Decision template deleted.");
              await reload();
            } catch (err) {
              showToast(toErrorMessage(err, "Could not delete decision template."), "error");
            }
          }}
          onCancel={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
