const NO_TEMPLATES: DecisionTemplate[] = [];

/** Sortable value of each sortable column of the template table. */
const TEMPLATE_SORT_VALUES: Record<string, (template: DecisionTemplate) => SortValue> = {
  name: (t) => t.name,
  description: (t) => t.description || null,
};

/**
 * Module: modules/decisions/DecisionTemplatesPanel
 *
 * The organisation-scoped Decision Template library, registered as `orgResourceSections` (`module.ts`): authored
 * content projects start new decisions from, so it sits on Org Resources, not Organisation Settings. An organisation
 * administrator manages it after creation (editing a seeded pack, adding or removing a template); the opt-in
 * template-pack picker at creation is in `pages/ServerOrganisationsPage.tsx` (`GET /orgs/creation-choices`).
 *
 * `DirectoryTable` + `Modal` create/edit (`DecisionTemplateFormModal`) + `ConfirmDialog` delete, as `EvidencePanel.tsx`,
 * without a detail `SidePanel` (a template has no sub-resources; edit reopens the form). Row actions (Edit, Delete) are
 * a per-row `ActionMenu` in an Actions column (style guide "Pattern: action menu" and "Pattern: directory table"): no
 * action is reachable only through a row click. The row stays clickable as a shortcut to the edit form, and "Edit" is
 * still in the menu.
 */
import { useState } from "react";
import { Pencil, Trash2 } from "lucide-react";

import { ActionMenu } from "../../components/ActionMenu";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as decisionsApi from "./api";
import { DecisionTemplateFormModal } from "./DecisionTemplateFormModal";
import type { DecisionTemplate } from "./types";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useTableSort } from "../../hooks/useTableSort";
import type { SortValue } from "../../utils/sortRows";

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

  useLoadOnChange(reload, [orgId]);

  const table = useTableSort(templates ?? NO_TEMPLATES, TEMPLATE_SORT_VALUES);
  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (templates === null) return <Spinner />;

  const columns: DirectoryColumn<DecisionTemplate>[] = [
    { key: "name", label: "Name", sortable: true, render: (t) => t.name },
    { key: "description", label: "Description", sortable: true, render: (t) => t.description || "—" },
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
        rows={table.rows}
        sort={table.sort}
        onSort={table.onSort}
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
