import { LINK_FLOW_LABEL, type ProjectLinkType } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { Badge } from "./Badge";

/**
 * One link type a project sees but does not own: the organisation's, or a
 * parent project's. Read-only apart from Hide/Show, which only removes the type
 * from this project's pickers; links already using it keep showing. Badges
 * state where it comes from (never a bare name) and whether it is hidden, by
 * this project or an ancestor, or not offered because a same-named type takes
 * precedence (style guide: every override says so, out loud).
 */
export function ProjectLinkTypeRow({
  item,
  canChange,
  onSetHidden,
}: {
  item: ProjectLinkType;
  /** False while the organisation locks customisation: no Hide/Show control. */
  canChange: boolean;
  onSetHidden: (hidden: boolean) => Promise<void>;
}) {
  const strings = useStrings();
  const scopeLabel =
    item.scope === "organization"
      ? strings.orgAdmin.linkTypeScopeOrganization
      : item.owner_project_name
        ? strings.orgAdmin.linkTypeInheritedFrom(item.owner_project_name)
        : strings.orgAdmin.linkTypeScopeInherited;
  const shadowed = item.shadowed_by_scope !== null;

  return (
    <div
      className="row"
      style={{ justifyContent: "space-between", borderBottom: "1px solid var(--color-border)", paddingBottom: "0.5rem" }}
    >
      <div className="row" style={{ gap: "0.5rem", opacity: item.hidden || shadowed ? 0.7 : 1 }}>
        <strong>{item.forward_name}</strong>
        <span className="text-muted">{item.reverse_name}</span>
        <Badge>{scopeLabel}</Badge>
        <Badge>{LINK_FLOW_LABEL[item.flow]}</Badge>
        {item.hidden && (
          <Badge>{item.hidden_by_inherited ? strings.orgAdmin.linkTypeHiddenByParent : strings.orgAdmin.linkTypeHidden}</Badge>
        )}
        {shadowed && <Badge>{strings.orgAdmin.linkTypeShadowed(item.shadowed_by_name ?? "")}</Badge>}
      </div>
      {canChange && !shadowed && (
        <button
          className="btn"
          aria-label={item.hidden ? strings.orgAdmin.linkTypeShowLabel(item.forward_name) : strings.orgAdmin.linkTypeHideLabel(item.forward_name)}
          onClick={() => void onSetHidden(!item.hidden)}
        >
          {item.hidden ? strings.orgAdmin.linkTypeShow : strings.orgAdmin.linkTypeHide}
        </button>
      )}
    </div>
  );
}
