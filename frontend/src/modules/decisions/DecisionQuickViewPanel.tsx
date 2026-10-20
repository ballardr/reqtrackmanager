/**
 * Module: modules/decisions/DecisionQuickViewPanel
 *
 * A minimal, read-only `SidePanel` peek at a Decision, opened on row click
 * from `ProjectDecisionsPage.tsx`'s list — the
 * "quick view + full page" pattern (docs/ux-style-guide.md's "Pattern:
 * entity detail panel"): a Decision's full detail (lifecycle actions,
 * relationships, comments, attachments) is too much for a side panel alone,
 * so that content now lives on `DecisionDetailPage.tsx` instead. This panel
 * only shows enough to identify the row and decide whether to open it —
 * code, status, title, type, the decision statement, and who owns it and
 * makes the call (a user or a group) — with no
 * edit/lifecycle controls of its own (this pattern's own "open it
 * read-only" rule), and a single "View full details" link into the page.
 */
import { Link } from "react-router-dom";

import { PrincipalBadge } from "../../components/PrincipalBadge";
import { RecordFieldGroup } from "../../components/RecordDetailParts";
import { SidePanel } from "../../components/SidePanel";
import { DECISION_STATUS_LABEL, DECISION_STATUS_TONE } from "./types";
import type { Decision, DecisionTypeDefinition } from "./types";
import { Badge } from "../../components/Badge";

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
        <Badge tone={DECISION_STATUS_TONE[decision.status]}>
          {DECISION_STATUS_LABEL[decision.status]}
        </Badge>
        <h2 style={{ margin: 0 }}>{decision.title}</h2>
        <p className="text-muted" style={{ margin: 0 }}>{decisionType?.name ?? "—"}</p>
        <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{decision.decision_statement}</p>
        <RecordFieldGroup helpNotNeeded label="Owner"><PrincipalBadge principal={decision.owner} /></RecordFieldGroup>
        <RecordFieldGroup helpNotNeeded label="Decision maker"><PrincipalBadge principal={decision.decision_maker} /></RecordFieldGroup>
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
