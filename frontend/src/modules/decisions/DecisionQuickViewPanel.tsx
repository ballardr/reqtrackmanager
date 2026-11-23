/**
 * Module: modules/decisions/DecisionQuickViewPanel
 *
 * A minimal, read-only `SidePanel` peek at a Decision, opened on row click from `ProjectDecisionsPage.tsx`: the "quick
 * view + full page" pattern (`docs/ux-style-guide.md` "Pattern: entity detail panel"). A Decision's lifecycle actions,
 * relationships, comments and attachments are too much for a side panel, so they are on `DecisionDetailPage.tsx`. This
 * panel shows only enough to identify the row and decide whether to open it (code, status, title, type, the decision
 * statement, and the owner and decision maker, each a user or a group), has no edit or lifecycle controls, and has
 * one "View full details" link into the page.
 */
import { Link } from "react-router-dom";

import { MarkdownView } from "../../components/MarkdownView";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { RecordFieldGroup } from "../../components/RecordDetailParts";
import { SidePanel } from "../../components/SidePanel";
import { DECISION_STATUS_LABEL, DECISION_STATUS_TONE } from "./types";
import type { Decision, DecisionTypeDefinition } from "./types";
import { Badge } from "../../components/Badge";
import { DECISIONS_HELP } from "./help";

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
        <MarkdownView math text={decision.decision_statement} />
        <RecordFieldGroup help={DECISIONS_HELP.decisionOwner} label="Owner"><PrincipalBadge principal={decision.owner} /></RecordFieldGroup>
        <RecordFieldGroup help={DECISIONS_HELP.decisionMaker} label="Decision maker"><PrincipalBadge principal={decision.decision_maker} /></RecordFieldGroup>
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
