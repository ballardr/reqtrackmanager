import { FolderKanban, User, Users } from "lucide-react";

import type { Principal, PrincipalType } from "../api/types";
import { PRINCIPAL_TYPE_LABEL } from "../api/types";

const ICON: Record<PrincipalType, typeof User> = { user: User, org_group: Users, project_group: FolderKanban };

/**
 * How a record shows who owns it: a user's name, or a group's name with its kind and how many people
 * it stands for, so an owner group is never mistaken for one person. The one rendering for every
 * owner/assignee/reviewer field (`PrincipalPicker` shows it for the current value).
 *
 * @param principal The resolved principal from the API (`PrincipalOut`).
 * @param placeholder Shown when the field is empty.
 */
export function PrincipalBadge({ principal, placeholder = "Unassigned" }: { principal: Principal | null | undefined; placeholder?: string }) {
  if (!principal) return <span className="text-muted">{placeholder}</span>;
  const Icon = ICON[principal.type];
  const kind = PRINCIPAL_TYPE_LABEL[principal.type];
  const detail =
    principal.type === "user"
      ? null
      : !principal.exists
        ? "deleted"
        : principal.member_count === null
          ? null
          : `${principal.member_count} ${principal.member_count === 1 ? "member" : "members"}`;
  return (
    <span className="row" style={{ gap: "0.35rem", alignItems: "center" }} title={detail ? `${kind}: ${principal.label}` : kind}>
      <Icon size={14} aria-hidden="true" />
      <span>{principal.label}</span>
      {principal.type !== "user" && <span className="badge badge--muted">{detail ? `${kind} · ${detail}` : kind}</span>}
    </span>
  );
}
