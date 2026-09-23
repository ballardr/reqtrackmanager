/**
 * Module: components/AddMembersModal
 *
 * Shared "staged multi-add" member picker — extracted from two near-
 * identical bespoke modals (`OrgAdminPage.tsx`'s "Manage users" add-member
 * step and `ProjectAdminPage.tsx`'s own Members-section add-member modal)
 * that both wrapped `UserAutocomplete` around an immediate-submit-per-
 * selection flow: picking a person/group/email fired one `POST` and closed
 * the modal on the spot, so adding three people cost three full round
 * trips and three modal open/close cycles, and the role `<select>` had to
 * be set *before* picking anyone since selection submitted immediately.
 *
 * Modeled on `ResourcePickerModal`'s existing staged-review precedent
 * (checkbox list + one "Attach selected" commit, not one call per item) —
 * see that component's own docstring — but each staged entry here also
 * carries its own role, editable per-row before committing, since adding a
 * person and picking their role are two separate decisions rather than one
 * shared "checked or not" state.
 *
 * Commit behaviour follows the style guide's "Pattern: bulk operations on
 * a list" tail exactly, even though this isn't a `DirectoryTable` selection
 * — no batch backend endpoint exists (`POST /{project_id}/roles` grants
 * one role to one user at a time; checked directly against
 * `backend/app/routers/projects.py::assign_project_role` before building
 * this), so committing loops the caller's own single-entry `onAddEntry`
 * sequentially, once per staged row, tolerating individual failures rather
 * than aborting the batch. A row that fails stays staged with its own
 * inline error and can be retried (press the commit button again) or
 * removed; rows that succeed disappear from the staged list immediately so
 * a partial failure is visible as "these two went through, this one
 * didn't," never a silent partial success. `onCommitted` fires once after
 * every row in a commit pass has settled, so callers can do one shared
 * reload (re-fetch the member list) instead of one reload per row — the
 * granular per-row `onAddEntry` stays a single-purpose "make this one grant
 * happen" call with no reload of its own.
 *
 * Preserves `ProjectAdminPage.tsx`'s extra "add into an existing
 * `ProjectGroup`" branch as a variant rather than dropping it: passing
 * `projectGroups` (mirroring `UserAutocomplete`'s own optional third match
 * kind) lets a project-group name also match in the picker, but selecting
 * one is a fundamentally different action from staging a member — it names
 * a *destination*, not a person to add, and grants no role at all (a
 * group's roles are separate, possibly-zero, possibly-several grants). So
 * it doesn't go through the staged list; it calls `onSelectProjectGroup`
 * directly and the caller re-renders this same component in its "roleless,
 * add into that group" configuration (`showRole={false}`, `groups`/`users`
 * narrowed to non-members, `onAddEntry` calling the existing
 * `addGroupMember`/`addOrgGroupMember` endpoint) — two configurations of
 * one component, not two components.
 */
import { useState, type ReactNode } from "react";

import type { OrgGroup, OrgUser, ProjectGroup, ProjectRole } from "../api/types";
import { PROJECT_ROLE_LABEL } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { Modal } from "./Modal";
import { UserAutocomplete } from "./UserAutocomplete";

export type StagedMemberKind = "user" | "group" | "external";

export interface StagedMember {
  /** `${kind}:${id}` — doubles as the row's React key and de-duplicates a
   * second pick of the same person/group/email while still staged. */
  key: string;
  kind: StagedMemberKind;
  /** `OrgUser.user_id` | `OrgGroup.id` | an email address, per `kind`. */
  id: string;
  /** Display label for the staged row — a name+email for a user, a plain
   * name for a group, or the bare email for an external invite. */
  label: string;
  /** Ignored by this component when `showRole` is false; still populated
   * (to `defaultRole`) so a caller's `onAddEntry` always receives a
   * well-typed `ProjectRole`, whether or not it acts on it. */
  role: ProjectRole;
}

type RowState = { status: "idle" | "pending" | "error"; error?: string };

export function AddMembersModal({
  title,
  onClose,
  users,
  groups,
  projectGroups,
  organizationId,
  projectId,
  defaultRole = "member",
  showRole = true,
  hint,
  onAddEntry,
  onCommitted,
  onSelectProjectGroup,
  onBack,
}: {
  title: string;
  onClose: () => void;
  /** Candidates `UserAutocomplete` matches by name/email — see that
   * component's own docstring for the client-side-vs-server-side-search
   * modes this list feeds. */
  users: OrgUser[];
  /** Org groups `UserAutocomplete` also matches by name. Omit to keep this
   * instance user/external-only. */
  groups?: OrgGroup[];
  /** This project's own groups, matched as a third kind purely to detect a
   * "take me to that group instead" pick — see module docstring. Omit to
   * keep this instance without project-group hand-off. */
  projectGroups?: ProjectGroup[];
  organizationId?: string;
  projectId?: string;
  /** Pre-selected role for a freshly-staged row — still overridable per
   * row via that row's own `<select>` before committing. */
  defaultRole?: ProjectRole;
  /** False for the "add into an existing ProjectGroup" variant, where
   * membership itself is granted with no role attached — hides the
   * per-row role `<select>` entirely rather than showing a control with no
   * effect. */
  showRole?: boolean;
  /** Optional explanatory copy shown above the picker (e.g. "Adding
   * someone here makes them a member of X — it does not grant a role by
   * itself."). */
  hint?: ReactNode;
  /** Called once per staged row when the commit button is pressed. A
   * thrown/rejected error keeps that row staged with the error shown
   * inline; a row that resolves is removed from the staged list
   * immediately. */
  onAddEntry: (entry: StagedMember) => Promise<void>;
  /** Called once after a commit pass finishes (whether or not every row
   * succeeded) — the caller's one shared place to re-fetch whatever list
   * this feeds, instead of once per row. */
  onCommitted?: () => void;
  /** Required alongside `projectGroups` — called with the matched project
   * group's id instead of staging anything. The caller is expected to
   * close or reconfigure this modal in response (see module docstring). */
  onSelectProjectGroup?: (groupId: string) => void;
  /** Shows a "Back" button alongside Cancel/commit, calling this instead of
   * `onClose` — for a caller that re-renders this component in a second
   * configuration (e.g. `ProjectAdminPage.tsx`'s project-group hand-off,
   * see module docstring) and wants a way back to the first one without a
   * full close. Omit for a plain single-step modal, unchanged from before
   * this prop existed. */
  onBack?: () => void;
}) {
  const strings = useStrings();
  const [staged, setStaged] = useState<StagedMember[]>([]);
  const [rowState, setRowState] = useState<Record<string, RowState>>({});
  const [committing, setCommitting] = useState(false);

  function stage(entry: Omit<StagedMember, "role">) {
    setStaged((prev) => (prev.some((e) => e.key === entry.key) ? prev : [...prev, { ...entry, role: defaultRole }]));
    setRowState((prev) => ({ ...prev, [entry.key]: { status: "idle" } }));
  }

  function removeStaged(key: string) {
    setStaged((prev) => prev.filter((e) => e.key !== key));
    setRowState((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }

  function setRole(key: string, role: ProjectRole) {
    setStaged((prev) => prev.map((e) => (e.key === key ? { ...e, role } : e)));
  }

  async function handleCommit() {
    setCommitting(true);
    const results = await Promise.allSettled(
      staged.map(async (entry) => {
        setRowState((prev) => ({ ...prev, [entry.key]: { status: "pending" } }));
        try {
          await onAddEntry(entry);
          return entry;
        } catch (err) {
          setRowState((prev) => ({
            ...prev,
            [entry.key]: { status: "error", error: err instanceof Error ? err.message : strings.common.error },
          }));
          throw entry;
        }
      })
    );
    const succeededKeys = new Set(
      results.filter((r): r is PromiseFulfilledResult<StagedMember> => r.status === "fulfilled").map((r) => r.value.key)
    );
    setStaged((prev) => prev.filter((e) => !succeededKeys.has(e.key)));
    setCommitting(false);
    onCommitted?.();
    if (succeededKeys.size === staged.length) {
      onClose();
    }
  }

  return (
    <Modal title={title} onClose={onClose} size="lg">
      <div className="stack">
        {hint && (
          <p className="text-muted" style={{ margin: 0 }}>
            {hint}
          </p>
        )}
        <div className="row" style={{ gap: "0.5rem", flexWrap: "wrap", alignItems: "flex-start" }}>
          <UserAutocomplete
            users={users.filter((u) => !staged.some((e) => e.kind === "user" && e.id === u.user_id))}
            placeholder={strings.admin.addOrInviteMemberPlaceholder}
            onSelect={(userId) => {
              const user = users.find((u) => u.user_id === userId);
              if (!user) return;
              stage({ key: `user:${userId}`, kind: "user", id: userId, label: `${user.display_name} (${user.email})` });
            }}
            groups={groups?.filter((g) => !staged.some((e) => e.kind === "group" && e.id === g.id))}
            onSelectGroup={
              groups
                ? (groupId) => {
                    const group = groups.find((g) => g.id === groupId);
                    if (!group) return;
                    stage({ key: `group:${groupId}`, kind: "group", id: groupId, label: group.name });
                  }
                : undefined
            }
            projectGroups={projectGroups}
            onSelectProjectGroup={onSelectProjectGroup}
            organizationId={organizationId}
            projectId={projectId}
            onSelectExternal={
              organizationId
                ? (email) => {
                    if (staged.some((e) => e.kind === "external" && e.id === email)) return;
                    stage({ key: `external:${email}`, kind: "external", id: email, label: email });
                  }
                : undefined
            }
          />
        </div>

        {staged.length === 0 ? (
          <p className="text-muted" style={{ margin: 0 }}>{strings.admin.addMembersStagedEmpty}</p>
        ) : (
          <ul className="stack" style={{ margin: 0, padding: 0, listStyle: "none", gap: "0.4rem" }}>
            {staged.map((entry) => {
              const state = rowState[entry.key] ?? { status: "idle" };
              return (
                <li key={entry.key} className="stack" style={{ gap: "0.15rem" }}>
                  <div className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
                    <span style={{ flex: 1, minWidth: 0 }}>{entry.label}</span>
                    {showRole && (
                      <select
                        className="input"
                        aria-label={strings.admin.roleForStagedMember(entry.label)}
                        value={entry.role}
                        onChange={(e) => setRole(entry.key, e.target.value as ProjectRole)}
                        disabled={state.status === "pending"}
                      >
                        <option value="project_manager">{PROJECT_ROLE_LABEL.project_manager}</option>
                        <option value="project_administrator">{PROJECT_ROLE_LABEL.project_administrator}</option>
                        <option value="stakeholder">{PROJECT_ROLE_LABEL.stakeholder}</option>
                        <option value="member">{PROJECT_ROLE_LABEL.member}</option>
                      </select>
                    )}
                    <button
                      type="button"
                      className="btn"
                      aria-label={strings.admin.removeStagedMember(entry.label)}
                      onClick={() => removeStaged(entry.key)}
                      disabled={state.status === "pending"}
                    >
                      {strings.common.remove}
                    </button>
                  </div>
                  {state.status === "error" && (
                    <div style={{ color: "var(--color-danger)", fontSize: "0.8rem" }}>{state.error}</div>
                  )}
                </li>
              );
            })}
          </ul>
        )}

        <div className="row" style={{ justifyContent: onBack ? "space-between" : "flex-end" }}>
          {onBack && (
            <button className="btn" onClick={onBack}>
              {strings.common.back}
            </button>
          )}
          <div className="row">
            <button className="btn" onClick={onClose}>
              {strings.common.cancel}
            </button>
            <button className="btn btn-primary" onClick={handleCommit} disabled={staged.length === 0 || committing}>
              {strings.admin.addSelectedMembers(staged.length)}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
}
