/**
 * Module: hooks/useServiceUserDialogs
 *
 * The dialogs of an organisation's service users, for the page that lists them with every other account (Organisation
 * Settings, Users): create, edit and a detail dialog per service user (tokens and lifecycle).
 *
 * Responsibilities:
 * - Create and save a service user from `ServiceUserFormModal`, and confirm each with a Toast.
 * - Read one service user when its row is opened, and re-read it after a change so the dialog shows the new state.
 * - Tell the caller when something changed so it reloads its list.
 *
 * Design decisions:
 * - The list is the caller's (the one Users list); this hook owns only the dialogs, so a service user is never
 *   listed twice with different actions.
 * - A created service user has no record code or page, so the Toast offers Open for its detail dialog (the same
 *   reason `useCreatedToast` offers Open: a sort or filter may put the new row out of sight), not a link.
 * - The projects for the token restriction are read on the first dialog opened, not on every visit to the list.
 *
 * Dependencies: `/api/v1/orgs/{id}/service-users`, `/api/v1/projects`.
 */
import { useCallback, useState, type ReactNode } from "react";

import { api } from "../api/client";
import { serviceUsersPath, type ServiceUser, type ServiceUserDraft } from "../api/serviceUsers";
import type { ProjectListItem } from "../api/types";
import { ServiceUserDetailModal } from "../components/ServiceUserDetailModal";
import { ServiceUserFormModal } from "../components/ServiceUserFormModal";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";

/** What the create and edit forms send: a blank address means "none", and an unset responsible party clears it. */
function payload(draft: ServiceUserDraft, forEdit: boolean) {
  const email = draft.email.trim() || null;
  return forEdit
    ? { name: draft.name.trim(), description: draft.description, email, responsible: draft.responsible }
    : { name: draft.name.trim(), description: draft.description, ...(email ? { email } : {}), responsible: draft.responsible };
}

/**
 * @param organizationId The organisation whose service users are administered.
 * @param onChanged Called after a service user is created or changed, so the caller reloads its list.
 * @returns `openCreate` and `openDetail(userId)` for the list's controls, and `dialogs` to render once in the page.
 */
export function useServiceUserDialogs({ organizationId, onChanged }: { organizationId: string; onChanged: () => void }): {
  openCreate: () => void;
  openDetail: (userId: string) => void;
  dialogs: ReactNode;
} {
  const strings = useStrings();
  const text = strings.serviceUsers;
  const { showToast } = useToast();
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<ServiceUser | null>(null);
  const [open, setOpen] = useState<ServiceUser | null>(null);
  const [projects, setProjects] = useState<ProjectListItem[] | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const ensureProjects = useCallback(async () => {
    if (projects) return;
    try {
      setProjects(await api.get<ProjectListItem[]>(`/api/v1/projects?archived=false&include_templates=false&organization_id=${organizationId}`));
    } catch {
      setProjects([]);
    }
  }, [organizationId, projects]);

  /** Reads one service user; `refresh` only updates a dialog still open on it, so a close that follows is not undone. */
  const show = useCallback(async (userId: string, refresh: boolean) => {
    try {
      const user = await api.get<ServiceUser>(`${serviceUsersPath(organizationId)}/${userId}`);
      setOpen((current) => (refresh && current?.user_id !== userId ? current : user));
    } catch (err) {
      showToast(toErrorMessage(err, text.loadFailed), "error");
    }
  }, [organizationId, showToast, text.loadFailed]);

  const openDetail = useCallback((userId: string) => {
    void ensureProjects();
    void show(userId, false);
  }, [ensureProjects, show]);

  const openCreate = useCallback(() => {
    setSaveError(null);
    setCreating(true);
  }, []);

  async function save(draft: ServiceUserDraft, existing: ServiceUser | null) {
    setSaveError(null);
    try {
      const saved = existing
        ? await api.patch<ServiceUser>(`${serviceUsersPath(organizationId)}/${existing.user_id}`, payload(draft, true))
        : await api.post<ServiceUser>(serviceUsersPath(organizationId), payload(draft, false));
      if (existing) {
        showToast(text.savedToast);
        setOpen(saved);
      } else {
        showToast(text.createdToast, "success", { action: { label: text.openAria(saved.name), onClick: () => openDetail(saved.user_id) } });
      }
      setCreating(false);
      setEditing(null);
      onChanged();
    } catch (err) {
      setSaveError(toErrorMessage(err, strings.common.error));
    }
  }

  const dialogs = (
    <>
      {creating && (
        <ServiceUserFormModal
          organizationId={organizationId} error={saveError} onCancel={() => setCreating(false)}
          onSave={(draft) => void save(draft, null)}
        />
      )}
      {editing && (
        <ServiceUserFormModal
          organizationId={organizationId} initial={editing} error={saveError} onCancel={() => setEditing(null)}
          onSave={(draft) => void save(draft, editing)}
        />
      )}
      {open && !editing && (
        <ServiceUserDetailModal
          organizationId={organizationId} serviceUser={open} projects={projects ?? []}
          onEdit={() => { setSaveError(null); setEditing(open); }}
          onChanged={() => { void show(open.user_id, true); onChanged(); }}
          onClose={() => setOpen(null)}
        />
      )}
    </>
  );

  return { openCreate, openDetail, dialogs };
}
