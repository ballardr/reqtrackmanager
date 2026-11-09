/**
 * Module: components/DisclosureRow
 *
 * One collapsible row of a stacked per-item list (a workflow, a stage's schedule): a toggle that names the item and
 * summarises it while closed, the item's own actions beside the toggle, and its detail beneath when open.
 *
 * Responsibilities:
 * - Render the header (chevron, title, optional summary) as one real button, with `actions` as a sibling so a control
 *   is never nested inside the toggle.
 * - Stay presentational: the open state is owned by the host, normally through `useDisclosureState`, so a list keeps
 *   its collapse choices in one stored value rather than one per row.
 *
 * Design decisions: it is the row-shaped counterpart of `CollapsibleSection` (a titled card for a page's top-level
 * sections) and uses the borderless `.disclosure-toggle` surface, so a row of a list never reads as a bordered chip.
 */
import { ChevronDown, ChevronRight } from "lucide-react";
import { useId, type ReactNode } from "react";

/**
 * @param title The item's name (kept visible when closed).
 * @param summary Short text beside the title that says what the row holds, shown while closed and open.
 * @param actions Controls for the item as a whole (edit, delete); never inside the toggle.
 * @param collapsed Whether the detail is hidden.
 * @param onToggle Called when the person opens or closes the row.
 * @param children The detail, rendered only while open.
 */
export function DisclosureRow({
  title, summary, actions, collapsed, onToggle, children,
}: {
  title: ReactNode;
  summary?: ReactNode;
  actions?: ReactNode;
  collapsed: boolean;
  onToggle: () => void;
  children: ReactNode;
}) {
  const contentId = useId();
  return (
    <div className="stack" style={{ borderBottom: "1px solid var(--color-border)", paddingBottom: "var(--space-3)" }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <button
          type="button" className="disclosure-toggle" style={{ flex: 1, minWidth: 0, width: "auto" }}
          aria-expanded={!collapsed} aria-controls={contentId} onClick={onToggle}
        >
          {collapsed ? <ChevronRight size={16} aria-hidden="true" /> : <ChevronDown size={16} aria-hidden="true" />}
          <strong>{title}</strong>
          {summary && <span className="text-muted">{summary}</span>}
        </button>
        {actions && <div className="row">{actions}</div>}
      </div>
      <div id={contentId} className="stack" hidden={collapsed}>{!collapsed && children}</div>
    </div>
  );
}
