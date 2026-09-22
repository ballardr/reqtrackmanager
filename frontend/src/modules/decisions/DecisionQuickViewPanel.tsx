/**
 * Module: modules/decisions/DecisionQuickViewPanel
 *
 * A minimal, read-only `SidePanel` peek at a Decision, opened on row click
 * from `ProjectDecisionsPage.tsx`'s list — Phase 9 (2026-09-22)'s
 * "quick view + full page" pattern (docs/ux-style-guide.md's "Pattern:
 * entity detail panel"): a Decision's full detail (lifecycle actions,
 * relationships, comments, attachments) is too much for a side panel alone,
 * so that content now lives on `DecisionDetailPage.tsx` instead. This panel
 * only shows enough to identify the row and decide whether to open it —
 * code, status, title, type, and the decision statement itself — with no
 * edit/lifecycle controls of its own (this pattern's own "open it
 * read-only" rule), and a single "View full details" link into the page.
 */
import { Link } from "react-router-dom";

import { SidePanel } from "../../components/SidePanel";
import { DECISION_STATUS_LABEL, DECISION_STATUS_TONE } from "./types";
import type { Decision, DecisionTypeDefinition } from "./types";

export function DecisionQuickViewPanel({
  projectId,
  decision,
  decisionTypes,
  onClose,
}: {
  projectId: string;
  decision: Decision;
  decisionTypes: DecisionTypeDefinition[];
  onClose: () => void;
}) {
  const decisionType = decisionTypes.find((t) => t.id === decision.decision_type_id);

  return (
    <SidePanel title={decision.unique_code} onClose={onClose}>
      <div className="stack">
        <span className={`badge badge--${DECISION_STATUS_TONE[decision.status]}`}>
          {DECISION_STATUS_LABEL[decision.status]}
        </span>
        <h2 style={{ margin: 0 }}>{decision.title}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{decisionType?.name ?? "—"}</p>
        <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{decision.decision_statement}</p>
        <Link
          to={`/projects/${projectId}/modules/decisions/${decision.id}`}
          className="btn btn-primary"
          style={{ alignSelf: "flex-start" }}
        >
          View full details
        </Link>
      </div>
    </SidePanel>
  );
}
