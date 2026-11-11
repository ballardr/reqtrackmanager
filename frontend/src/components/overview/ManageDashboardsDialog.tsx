/**
 * Module: components/overview/ManageDashboardsDialog
 *
 * The organisation administrator's list of dashboard pages: add a page, copy one, rename it, limit it to chosen people or groups,
 * put the pages in order and delete one. The built-in Overview page is always first; it can be limited but not renamed,
 * moved or deleted.
 *
 * Responsibilities:
 * - Show every page with who it is limited to, and the actions on it.
 * - Create and edit through one form (`DashboardFormDialog`), so the two cannot drift.
 * - Report each change through `onChanged` so the overview page reloads its menu.
 *
 * Design decisions: a page limited to nobody is shown to every member, which the form's help says; deleting asks first
 * because the layout cannot be recovered (the style guide's destructive-action tier).
 */
import { ArrowDown, ArrowUp, Copy, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api } from "../../api/client";
import type { OrgDashboard } from "../../api/types";
import { useStrings } from "../../context/TerminologyContext";
import { toErrorMessage } from "../../context/ToastContext";
import { useMutation } from "../../hooks/useMutation";
import { ConfirmDialog } from "../ConfirmDialog";
import { FormActions } from "../FormActions";
import { TextField } from "../FormFields";
import { Modal } from "../Modal";
import { PrincipalListField } from "../PrincipalListField";
import { PrincipalBadge } from "../PrincipalBadge";
import type { PrincipalRef } from "../../api/types";

/** The kinds of principal a page may be limited to: a project group belongs to a project, not an organisation. */
const VIEWER_KINDS = ["user", "org_group"] as const;

/**
 * The create and edit form of one page. A new page is created with its name (who may see it is set once it exists, so the
 * chosen people and groups show their names); an existing page's people and groups are saved as they are chosen, as
 * every list field is, and its name with Save.
 */
function DashboardFormDialog({
  organizationId, page, onClose, onSaved, onViewersChanged,
}: { organizationId: string; page: OrgDashboard | null; onClose: () => void; onSaved: () => void; onViewersChanged: () => void }) {
  const strings = useStrings();
  const t = strings.orgDashboards;
  const run = useMutation();
  const [name, setName] = useState(page?.name ?? "");
  const [error, setError] = useState<string | null>(null);
  const base = `/api/v1/orgs/${organizationId}/dashboards`;

  async function save() {
    setError(null);
    try {
      if (page) await api.put(`${base}/${page.id}`, { name: page.is_default ? undefined : name.trim() });
      else await api.post(base, { name: name.trim() });
    } catch (err) {
      setError(toErrorMessage(err, strings.mutation.failure("save", t.noun)));
      return;
    }
    onSaved();
  }

  async function setViewers(refs: PrincipalRef[]) {
    if (page && (await run(() => api.put(`${base}/${page.id}`, { viewers: refs }), "update", t.noun))) onViewersChanged();
  }

  return (
    <Modal title={page ? t.editTitle(page.name) : t.newTitle} onClose={onClose}>
      <div className="stack">
        <TextField
          helpNotNeeded required label={t.name} value={name} onChange={setName} disabled={page?.is_default === true}
          inputProps={{ maxLength: 100 }}
        />
        {page && (
          <PrincipalListField
            label={t.visibleTo} ariaLabel={t.visibleToAria} values={page.viewers} orgUsers={[]} organizationId={organizationId}
            kinds={VIEWER_KINDS} emptyText={t.visibleToEveryone} help={strings.help.dashboardViewers}
            onChange={(refs) => void setViewers(refs)}
          />
        )}
        <FormActions error={error} onCancel={onClose} onSave={() => void save()} saveDisabled={!name.trim() || page?.is_default === true} />
      </div>
    </Modal>
  );
}

/**
 * @param organizationId The organisation.
 * @param pages The pages as the administrator sees them (with viewers), in order.
 * @param onClose Called when the dialog is dismissed.
 * @param onChanged Called after any change, so the page reloads its menu and the open page.
 */
export function ManageDashboardsDialog({
  organizationId, pages, onClose, onChanged,
}: { organizationId: string; pages: OrgDashboard[]; onClose: () => void; onChanged: () => void }) {
  const strings = useStrings();
  const t = strings.orgDashboards;
  const run = useMutation();
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [removing, setRemoving] = useState<OrgDashboard | null>(null);
  const base = `/api/v1/orgs/${organizationId}/dashboards`;
  const movable = pages.filter((p) => !p.is_default);

  async function move(page: OrgDashboard, delta: number) {
    const ids = movable.map((p) => p.id);
    const index = ids.indexOf(page.id);
    const target = index + delta;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target], ids[index]];
    if (await run(() => api.put(`${base}/order`, { ids }), "move", t.noun)) onChanged();
  }

  async function duplicate(page: OrgDashboard) {
    if (await run(() => api.post(`${base}/${page.id}/copy`, {}), "create", t.noun)) onChanged();
  }

  async function remove(page: OrgDashboard) {
    setRemoving(null);
    if (await run(() => api.delete(`${base}/${page.id}`), "delete", t.noun)) onChanged();
  }

  return (
    <Modal title={t.manageTitle} onClose={onClose} size="lg">
      <div className="stack">
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button type="button" className="btn btn-primary" onClick={() => setEditing("new")}><Plus /> {t.newPage}</button>
        </div>
        {pages.map((page) => {
          const index = movable.findIndex((p) => p.id === page.id);
          return (
            <div key={page.id} className="row" style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", paddingBottom: "var(--space-2)" }}>
              <div className="row" style={{ flexWrap: "wrap" }}>
                <strong>{page.name}</strong>
                {page.is_default && <span className="text-muted">{t.builtIn}</span>}
                {page.restricted
                  ? page.viewers.map((v) => <PrincipalBadge key={`${v.type}:${v.id}`} principal={v} />)
                  : <span className="text-muted">{t.visibleToEveryone}</span>}
              </div>
              <div className="row">
                {!page.is_default && (
                  <>
                    <button type="button" className="btn" disabled={index <= 0} onClick={() => void move(page, -1)} aria-label={t.moveUp(page.name)}><ArrowUp /></button>
                    <button type="button" className="btn" disabled={index === movable.length - 1} onClick={() => void move(page, 1)} aria-label={t.moveDown(page.name)}><ArrowDown /></button>
                  </>
                )}
                <button type="button" className="btn" onClick={() => setEditing(page.id)} aria-label={t.editAria(page.name)} title={t.editAria(page.name)}><Pencil /></button>
                <button type="button" className="btn" onClick={() => void duplicate(page)} aria-label={t.copyAria(page.name)} title={t.copyAria(page.name)}><Copy /></button>
                {!page.is_default && (
                  <button type="button" className="btn btn-danger" onClick={() => setRemoving(page)} aria-label={t.deleteAria(page.name)} title={t.deleteAria(page.name)}><Trash2 /></button>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {editing !== null && (
        <DashboardFormDialog
          organizationId={organizationId} page={editing === "new" ? null : pages.find((p) => p.id === editing) ?? null}
          onClose={() => setEditing(null)} onSaved={() => { setEditing(null); onChanged(); }} onViewersChanged={onChanged}
        />
      )}
      {removing && (
        <ConfirmDialog
          title={t.deleteTitle(removing.name)} message={t.deleteBody} confirmLabel={strings.common.delete}
          onConfirm={() => void remove(removing)} onCancel={() => setRemoving(null)}
        />
      )}
    </Modal>
  );
}
