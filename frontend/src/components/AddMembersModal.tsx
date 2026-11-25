/**
 * Module: components/AddMembersModal
 *
 * Shared staged multi-add member picker for the organisation and project member pages: each staged entry (person,
 * group or email) carries its own editable role and one commit adds them all (style guide "Pattern: bulk
 * operations on a list"). With no batch endpoint, commit loops the caller's `onAddEntry` once per row, tolerating
 * failures: a failed row stays staged with its inline error and can be retried or removed. `onCommitted` fires once
 * after every row settles, so the caller reloads once.
 *
 * With `projectGroups`, a group name also matches, but selecting one names a destination, not a person:
 * `onSelectProjectGroup` is called and the caller re-renders this component roleless (`showRole={false}`).
 */
import { useState, type ReactNode } from "react";

import type { OrgGroup, OrgUser, ProjectGroup, ProjectRole } from "../api/types";
import { PROJECT_ROLE_LABEL } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { Modal } from "./Modal";
import { UserAutocomplete } from "./UserAutocomplete";
import { FormActions } from "./FormActions";
import { InlineSelect } from "./LabeledSelect";

/** The roles a staged member may be given, in the order the role select lists them. */
const STAGED_ROLES: ProjectRole[] = ["project_manager", "project_administrator", "stakeholder", "member"];

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
  /** Organisation groups `UserAutocomplete` also matches by name. Omit to keep this
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
  /** False for the "add into an existing ProjectGroup" variant, where membership carries no role: hides the
   * per-row role `<select>`. */
  showRole?: boolean;
  /** Optional explanatory copy shown above the picker (e.g. "Adding
   * someone here makes them a member of X — it does not grant a role by
   * itself."). */
  hint?: ReactNode;
  /** Called once per staged row on commit. A rejected call keeps that row staged with the error shown inline; a
   * resolved one removes the row. */
  onAddEntry: (entry: StagedMember) => Promise<void>;
  /** Called once after a commit pass finishes (whether or not every row
   * succeeded) — the caller's one shared place to re-fetch whatever list
   * this feeds, instead of once per row. */
  onCommitted?: () => void;
  /** Required alongside `projectGroups` — called with the matched project
   * group's id instead of staging anything. The caller is expected to
   * close or reconfigure this modal in response (see module docstring). */
  onSelectProjectGroup?: (groupId: string) => void;
  /** Shows a "Back" button beside Cancel/commit, calling this instead of `onClose`: for a caller that re-renders
   * this component in a second configuration and wants a way back to the first. Omit for a single-step modal. */
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
        <div className="row" style={{ gap: "var(--space-3)", flexWrap: "wrap", alignItems: "flex-start" }}>
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
          <ul className="stack" style={{ margin: 0, padding: 0, listStyle: "none", gap: "var(--space-2)" }}>
            {staged.map((entry) => {
              const state = rowState[entry.key] ?? { status: "idle" };
              return (
                <li key={entry.key} className="stack" style={{ gap: "0.15rem" }}>
                  <div className="row" style={{ gap: "var(--space-3)", alignItems: "center" }}>
                    <span style={{ flex: 1, minWidth: 0 }}>{entry.label}</span>
                    {showRole && (
                      <InlineSelect<ProjectRole>
                        ariaLabel={strings.admin.roleForStagedMember(entry.label)}
                        value={entry.role}
                        placeholder={null}
                        onChange={(role) => setRole(entry.key, role)}
                        disabled={state.status === "pending"}
                        options={STAGED_ROLES.map((role) => ({ value: role, label: PROJECT_ROLE_LABEL[role] }))}
                      />
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

        <FormActions
          leading={onBack && <button className="btn" onClick={onBack}>{strings.common.back}</button>}
          onCancel={onClose}
          onSave={handleCommit}
          saveLabel={strings.admin.addSelectedMembers(staged.length)}
          saveDisabled={staged.length === 0 || committing}
        />
      </div>
    </Modal>
  );
}
