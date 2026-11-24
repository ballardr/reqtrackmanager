/**
 * Module: components/PrincipalBadge
 *
 * The one rendering of a principal (a user, an organisation group or a project group) in an owner, assignee,
 * reviewer or other person-valued field. The kind icon says whether it is a person or a group; a group's kind and
 * how many people it stands for are in a tooltip and in visually hidden text read before the name, so the row
 * is as wide as a user's and an icon alone is never the only signal.
 *
 * Dependencies: `CellText` (one line, ellipsis), `Tooltip`, `PRINCIPAL_TYPE_LABEL`.
 */
import { FolderKanban, User, Users } from "lucide-react";

import type { Principal, PrincipalType } from "../api/types";
import { PRINCIPAL_TYPE_LABEL } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { Badge } from "./Badge";
import { CellText } from "./CellText";
import { ServiceBadge } from "./ServiceBadge";
import { Tooltip } from "./Tooltip";

const ICON: Record<PrincipalType, typeof User> = { user: User, org_group: Users, project_group: FolderKanban };

/**
 * Shows who owns a record: the kind icon and the name on one line cut with an ellipsis (`CellText`), so a long
 * name never changes the shape of the row it sits in. A group's kind and member count are in the tooltip on the icon
 * and name and in hidden text before the name; a deleted group keeps a visible Deleted marker.
 *
 * @param principal The resolved principal from the API (`PrincipalOut`).
 * @param placeholder Shown when the field is empty.
 */
export function PrincipalBadge({ principal, placeholder = "Unassigned" }: { principal: Principal | null | undefined; placeholder?: string }) {
  const allStrings = useStrings();
  const strings = allStrings.principalBadge;
  if (!principal) return <span className="text-muted">{placeholder}</span>;
  const Icon = ICON[principal.type];
  const kind = PRINCIPAL_TYPE_LABEL[principal.type];
  const detail =
    principal.type === "user"
      ? undefined
      : principal.exists
        ? strings.groupDetail(kind, principal.member_count)
        : strings.deletedGroupDetail(kind);
  const icon = <Icon size={14} aria-hidden="true" style={{ flex: "none" }} />;
  return (
    <span className="row" style={{ gap: "var(--space-2)", alignItems: "center", flexWrap: "nowrap", minWidth: 0 }}>
      {detail ? <Tooltip label={detail} style={{ flex: "none" }}>{icon}</Tooltip> : icon}
      {detail && <span className="sr-only">{detail}</span>}
      <CellText detail={detail}>{principal.label}</CellText>
      {principal.imported && <Badge tone="warning">{allStrings.importPeople.importedBadge}</Badge>}
      {principal.service && <ServiceBadge />}
      {principal.type !== "user" && !principal.exists && <Badge tone="muted">{strings.deleted}</Badge>}
    </span>
  );
}
