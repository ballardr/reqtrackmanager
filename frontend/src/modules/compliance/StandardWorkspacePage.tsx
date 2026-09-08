/**
 * Module: modules/compliance/StandardWorkspacePage
 *
 * The per-standard workspace at `/standards/:standardId[/versions|/history]`
 * (docs/compliance-module-plan.md Phase 18) — the drill-down a row on
 * `StandardListPage.tsx` opens into. Structurally a sibling to a project's
 * own workspace (`Layout.tsx`'s "Standard" nav-rail section, rendered only
 * while a `standardId` is present in the URL — the same trigger pattern the
 * "Project" section already uses), not nested inside it: Overview/Details,
 * Versions (the existing `VersionWorkspace`, reused as-is via
 * `StandardVersionsSection`), and History.
 *
 * No org id is in this page's own URL — it resolves one first, via the new
 * `GET /api/v1/compliance/standards/{standard_id}` (`global_router.py`,
 * mirroring exactly how a project's own id resolves to its org today), then
 * threads that `organization_id` through to every existing org-scoped
 * nested call unchanged (versions, requirements, history, action types).
 *
 * Section switching uses a real route (`:section?`, defaulting to
 * "overview"), the same "a real URL, not client-only state" convention
 * `ProjectAdminPage.tsx`'s own `:group?` already establishes for its
 * `ResourceMenu` — here expressed as `NavRailLink`s instead, since a single
 * Standard is a project-like *entity*, not a fixed set of settings screens
 * (see docs/ux-style-guide.md's new "Pattern: project-like drill-down
 * entities" section for why this gets a nav-rail section while Action
 * Types/Mapping Types, a fixed pair of org-wide screens, get a
 * `ResourceMenu` instead on `ComplianceSettingsPage.tsx`).
 */
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";

import { api } from "../../api/client";
import { activityActionLabel } from "../../api/types";
import type { OrgUser } from "../../api/types";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import * as complianceApi from "./api";
import { refreshComplianceNavVisibility } from "./useComplianceNavVisibility";
import { StandardFormModal } from "./StandardFormModal";
import { StandardVersionsSection } from "./StandardVersionsSection";
import type { ComplianceActionType, ComplianceAuditEvent, ComplianceStandard } from "./types";
import { userDisplayName } from "./types";

type StandardWorkspaceSection = "overview" | "versions" | "history";

export function StandardWorkspacePage() {
  const { standardId, section: sectionParam } = useParams<{ standardId: string; section?: string }>();
  const { showToast } = useToast();

  const [standard, setStandard] = useState<ComplianceStandard | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [actionTypes, setActionTypes] = useState<ComplianceActionType[]>([]);
  const [orgUsers, setOrgUsers] = useState<OrgUser[]>([]);
  const [editing, setEditing] = useState(false);
  const [editError, setEditError] = useState<string | null>(null);
  const [confirmingArchive, setConfirmingArchive] = useState(false);
  const [history, setHistory] = useState<ComplianceAuditEvent[] | null>(null);

  const section: StandardWorkspaceSection =
    sectionParam === "versions" || sectionParam === "history" ? sectionParam : "overview";

  async function reloadStandard() {
    if (!standardId) return;
    try {
      const loaded = await complianceApi.getStandardById(standardId);
      setStandard(loaded);
      setNotFound(false);
    } catch {
      setNotFound(true);
    }
  }

  useEffect(() => {
    setStandard(null);
    setNotFound(false);
    void reloadStandard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [standardId]);

  useEffect(() => {
    if (!standard) return;
    complianceApi.listActionTypes(standard.organization_id).then(setActionTypes);
    api.get<OrgUser[]>(`/api/v1/orgs/${standard.organization_id}/users`).then(setOrgUsers);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [standard?.organization_id]);

  useEffect(() => {
    if (section !== "history" || !standard) return;
    setHistory(null);
    complianceApi
      .getStandardHistory(standard.organization_id, standard.id)
      .then(setHistory)
      .catch((err) => showToast(toErrorMessage(err, "Could not load history."), "error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [section, standard?.organization_id, standard?.id]);

  async function handleArchiveToggle() {
    if (!standard) return;
    try {
      const updated = standard.is_archived
        ? await complianceApi.unarchiveStandard(standard.organization_id, standard.id)
        : await complianceApi.archiveStandard(standard.organization_id, standard.id);
      showToast(updated.is_archived ? "Standard archived." : "Standard unarchived.");
      setStandard(updated);
      refreshComplianceNavVisibility();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not update standard."), "error");
    } finally {
      setConfirmingArchive(false);
    }
  }

  if (notFound) {
    return <p className="text-muted">This compliance standard could not be found, or you don't have access to it.</p>;
  }
  if (!standard) return <Spinner />;

  return (
    <div className="stack">
      <div className="stack" style={{ gap: "0.15rem" }}>
        <h1 style={{ margin: 0 }}>{standard.reference} — {standard.name}</h1>
        {standard.is_archived && <span className="badge">Archived</span>}
      </div>

      {section === "overview" && (
        <div className="card stack">
          <p>{standard.description || <span className="text-muted">No description.</span>}</p>
          {standard.issuing_organisation && <p className="text-muted">Issued by {standard.issuing_organisation}</p>}
          <div className="row">
            <button className="btn" onClick={() => setEditing(true)}>Edit</button>
            <button className="btn btn-danger" onClick={() => setConfirmingArchive(true)}>
              {standard.is_archived ? "Unarchive" : "Archive"}
            </button>
          </div>
        </div>
      )}

      {section === "versions" && (
        <StandardVersionsSection orgId={standard.organization_id} standard={standard} actionTypes={actionTypes} />
      )}

      {section === "history" && (
        history === null ? (
          <Spinner />
        ) : history.length === 0 ? (
          <p className="text-muted">No history yet.</p>
        ) : (
          <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
            {history.map((h) => (
              <li key={h.id} style={{ borderBottom: "1px solid var(--color-border)", padding: "0.4rem 0" }}>
                <span className="text-muted">{new Date(h.created_at).toLocaleString()}</span>
                {" — "}
                {userDisplayName(orgUsers, h.actor_id)} — {activityActionLabel(h.action)}
              </li>
            ))}
          </ul>
        )
      )}

      {editing && (
        <StandardFormModal
          initial={standard}
          orgId={standard.organization_id}
          error={editError}
          onCancel={() => {
            setEditing(false);
            setEditError(null);
          }}
          onSave={async (values) => {
            setEditError(null);
            try {
              const updated = await complianceApi.updateStandard(standard.organization_id, standard.id, {
                ...values,
                owner_id: standard.owner_id,
              } as { name: string; description: string; issuing_organisation: string | null; owner_id: string });
              showToast("Standard updated.");
              setEditing(false);
              setStandard(updated);
            } catch (err) {
              setEditError(toErrorMessage(err, "Could not update standard."));
            }
          }}
        />
      )}

      {confirmingArchive && (
        <ConfirmDialog
          title={standard.is_archived ? `Unarchive "${standard.name}"?` : `Archive "${standard.name}"?`}
          message={
            standard.is_archived
              ? "This standard will reappear in the default (non-archived) list."
              : "This standard will be hidden from the default list. Nothing referencing it is deleted."
          }
          confirmLabel={standard.is_archived ? "Unarchive" : "Archive"}
          onConfirm={handleArchiveToggle}
          onCancel={() => setConfirmingArchive(false)}
        />
      )}
    </div>
  );
}
