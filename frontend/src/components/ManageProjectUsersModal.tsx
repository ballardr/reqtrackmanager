/**
 * Module: components/ManageProjectUsersModal
 *
 * The "Manage users" dialog for one project: the shared `ProjectMembersTable` (the same one the project's own
 * Members section renders) with the staged add-member control, opened by an organisation administrator for a project
 * they hold no role in (the gear on a non-member row of the project list).
 *
 * Responsibilities:
 * - Loads the project's effective members, group roles, pending invitations and available module roles when it
 *   opens, and the organisation's users and groups for the add-member control.
 * - Applies each change (role toggles, group roles, removal, conversion to direct roles, resending an invitation)
 *   through the existing project endpoints, re-reading the affected list and reporting failures as toasts.
 *
 * Design decisions:
 * - No new endpoint and no new permission: every call is one the Members section already makes, so the
 *   `require_project_view_or_manage` check applies on each, exactly as before.
 * - Self-contained: it takes the project and an `onClose`, so any page can open it without owning its state.
 *
 * Dependencies: `api/client`, `ProjectMembersTable`, `AddMembersModal`, `Modal`, the toast and branding contexts.
 */
import { Plus } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { api } from "../api/client";
import type {
  AssignByEmailOutcome,
  EffectiveMember,
  MaterializeResult,
  ModuleRoleDefinition,
  OrgGroup,
  OrgGroupProjectRoleSummary,
  OrgUser,
  PendingInvite,
  ProjectRole,
} from "../api/types";
import { useOrgLabel } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { AddMembersModal, type StagedMember } from "./AddMembersModal";
import { Modal } from "./Modal";
import { ProjectMembersTable } from "./ProjectMembersTable";
import { Spinner } from "./Spinner";

const USERS_PAGE_SIZE = 30;

interface ManageProjectUsersModalProps {
  /** The project whose users are managed. */
  project: { id: string; name: string; organization_id: string };
  /** Called when the dialog is dismissed. */
  onClose: () => void;
}

/**
 * Dialog for managing who holds a role on one project.
 *
 * @param props.project The project, with the organisation it belongs to.
 * @param props.onClose Called to close the dialog.
 * @returns The dialog, with a spinner until the project's access has loaded.
 */
export function ManageProjectUsersModal({ project, onClose }: ManageProjectUsersModalProps) {
  const strings = useStrings();
  const { showToast } = useToast();
  const orgLabel = useOrgLabel();
  const base = `/api/v1/projects/${project.id}`;
  const [members, setMembers] = useState<EffectiveMember[] | null>(null);
  const [groupRoles, setGroupRoles] = useState<OrgGroupProjectRoleSummary[]>([]);
  const [invites, setInvites] = useState<PendingInvite[]>([]);
  const [moduleRoles, setModuleRoles] = useState<ModuleRoleDefinition[]>([]);
  const [users, setUsers] = useState<OrgUser[]>([]);
  const [groups, setGroups] = useState<OrgGroup[]>([]);
  const [resendingInviteId, setResendingInviteId] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get<EffectiveMember[]>(`${base}/effective-members`),
      api.get<OrgGroupProjectRoleSummary[]>(`${base}/group-roles`),
      api.get<PendingInvite[]>(`${base}/pending-invites`),
      api.get<ModuleRoleDefinition[]>(`${base}/module-roles`),
      api.getPage<OrgUser>(`/api/v1/orgs/${project.organization_id}/users?limit=${USERS_PAGE_SIZE}&offset=0`),
      api.get<OrgGroup[]>(`/api/v1/orgs/${project.organization_id}/groups`),
    ])
      .then(([loadedMembers, loadedGroupRoles, loadedInvites, loadedModuleRoles, userPage, loadedGroups]) => {
        if (cancelled) return;
        setMembers(loadedMembers);
        setGroupRoles(loadedGroupRoles);
        setInvites(loadedInvites);
        setModuleRoles(loadedModuleRoles);
        setUsers(userPage.items);
        setGroups(loadedGroups);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(toErrorMessage(err, strings.common.error));
      });
    return () => {
      cancelled = true;
    };
  }, [base, project.organization_id, strings.common.error]);

  const reloadMembers = useCallback(async () => {
    setMembers(await api.get<EffectiveMember[]>(`${base}/effective-members`));
  }, [base]);
  const reloadGroupRoles = useCallback(async () => {
    setGroupRoles(await api.get<OrgGroupProjectRoleSummary[]>(`${base}/group-roles`));
  }, [base]);
  const reloadInvites = useCallback(async () => {
    setInvites(await api.get<PendingInvite[]>(`${base}/pending-invites`));
  }, [base]);

  /** Runs one change and reports a failure as a toast; the caller re-reads what the change affected. */
  async function attempt(change: () => Promise<void>) {
    try {
      await change();
    } catch (err) {
      showToast(toErrorMessage(err, strings.common.error), "error");
    }
  }

  const toggleRole = (userId: string, role: ProjectRole, checked: boolean) =>
    attempt(async () => {
      if (checked) await api.post(`${base}/roles`, { user_id: userId, role });
      else await api.delete(`${base}/roles/${userId}/${role}`);
      await reloadMembers();
    });

  const toggleModuleRole = (userId: string, moduleKey: string, roleKey: string, grant: boolean) =>
    attempt(async () => {
      if (grant) await api.post(`${base}/members/${userId}/module-roles`, { module_key: moduleKey, role_key: roleKey });
      else await api.delete(`${base}/members/${userId}/module-roles/${moduleKey}/${roleKey}`);
      await reloadMembers();
    });

  const toggleGroupRole = (orgGroupId: string, role: ProjectRole, checked: boolean) =>
    attempt(async () => {
      if (checked) await api.post(`${base}/group-roles`, { org_group_id: orgGroupId, role });
      else await api.delete(`${base}/group-roles/${orgGroupId}/${role}`);
      await reloadGroupRoles();
      await reloadMembers();
    });

  const removeGroup = (orgGroupId: string) =>
    attempt(async () => {
      const group = groupRoles.find((g) => g.org_group_id === orgGroupId);
      if (!group) return;
      await Promise.all(group.roles.map((role) => api.delete(`${base}/group-roles/${orgGroupId}/${role}`)));
      showToast(strings.membersTable.removeGroupSuccess(group.org_group_name));
      await reloadGroupRoles();
      await reloadMembers();
    });

  const removeAllAccess = (userId: string) =>
    attempt(async () => {
      const member = members?.find((m) => m.user_id === userId);
      if (!member) return;
      const roles = [...new Set(member.sources.map((s) => s.role))];
      await Promise.all(roles.map((role) => api.delete(`${base}/roles/${userId}/${role}`)));
      showToast(strings.membersTable.removeAllAccessSuccess(member.display_name));
      await reloadMembers();
    });

  const convertToDirect = (userId: string) =>
    attempt(async () => {
      const name = members?.find((m) => m.user_id === userId)?.display_name ?? "";
      const result = await api.post<MaterializeResult>(`${base}/materialize-inherited-access/${userId}`);
      showToast(
        result.created.length > 0
          ? strings.membersTable.convertToDirectSuccess(name)
          : strings.membersTable.convertToDirectNoOp(name),
      );
      await reloadMembers();
    });

  const resendInvite = (invite: PendingInvite) => {
    setResendingInviteId(invite.id);
    return attempt(async () => {
      await api.post(`${base}/pending-invites/${invite.id}/resend`);
      showToast(strings.admin.resendInviteSuccess(invite.email));
      await reloadInvites();
    }).finally(() => setResendingInviteId(null));
  };

  /** One staged entry of the add control; left to throw so the entry shows its own error inline. */
  async function addEntry(entry: StagedMember) {
    if (entry.kind === "user") {
      await api.post(`${base}/roles`, { user_id: entry.id, role: entry.role });
    } else if (entry.kind === "group") {
      await api.post(`${base}/group-roles`, { org_group_id: entry.id, role: entry.role });
    } else {
      const result = await api.post<{ outcome: AssignByEmailOutcome }>(`${base}/roles/by-email`, {
        email: entry.id,
        role: entry.role,
      });
      const messages: Record<AssignByEmailOutcome, (email: string, role: string, org: string) => string> = {
        added: strings.admin.externalAddedDirectly,
        invited: strings.admin.externalInvited,
        sso_provisioned: strings.admin.externalSsoProvisioned,
      };
      showToast(messages[result.outcome](entry.id, entry.role, orgLabel));
    }
  }

  /** Re-reads everything a successful add may have changed, once per commit pass. */
  async function addCommitted() {
    await Promise.all([reloadMembers(), reloadGroupRoles(), reloadInvites()]);
  }

  return (
    <Modal title={strings.orgAdmin.manageUsersModalTitle(project.name)} onClose={onClose} size="lg">
      {loadError && <p className="text-danger" role="alert">{loadError}</p>}
      {!loadError && members === null && <Spinner />}
      {members !== null && (
        <>
          <div className="row" style={{ gap: "var(--space-3)", flexWrap: "wrap" }}>
            <button className="btn btn-primary" onClick={() => setAddOpen(true)}>
              <Plus /> {strings.admin.addMember}
            </button>
          </div>
          {addOpen && (
            <AddMembersModal
              title={strings.admin.addMember}
              onClose={() => setAddOpen(false)}
              users={users}
              groups={groups}
              organizationId={project.organization_id}
              projectId={project.id}
              onAddEntry={addEntry}
              onCommitted={addCommitted}
            />
          )}
          <ProjectMembersTable
            members={members}
            invites={invites}
            groupRoles={groupRoles}
            onToggleRole={toggleRole}
            onToggleGroupRole={toggleGroupRole}
            onResendInvite={resendInvite}
            resendingInviteId={resendingInviteId}
            onRemoveAllAccess={removeAllAccess}
            onConvertToDirect={convertToDirect}
            onRemoveGroup={removeGroup}
            ariaLabel={strings.orgAdmin.manageUsers}
            availableModuleRoles={moduleRoles}
            onToggleModuleRole={toggleModuleRole}
          />
        </>
      )}
    </Modal>
  );
}
