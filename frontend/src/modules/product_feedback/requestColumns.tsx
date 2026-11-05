/**
 * Module: modules/product_feedback/requestColumns
 *
 * The table columns the project list and the organisation inbox share. Demand sits beside the score, never inside it.
 * A request with no Pain Point carries a warning (a solution with no stated problem), never a block.
 */
import type { ReactNode } from "react";

import type { ScoringScheme } from "../../api/scoring";
import { Badge } from "../../components/Badge";
import type { DirectoryColumn } from "../../components/DirectoryTable";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { RequestScoreBadge } from "./RequestScoreBadge";
import { demandText } from "./requestListState";
import { REQUEST_STATUS_LABEL, REQUEST_STATUS_TONE } from "./types";
import type { EnhancementRequest } from "./types";

/**
 * The columns of a request list.
 *
 * @param scheme The scoring scheme in effect (model labels for the score columns).
 * @param models The model keys to show a score column for.
 * @param titleExtra Extra content after a row's title (the project list adds the scope label).
 * @param codeCell How a row's code is shown (a project code, or the organisation-qualified one for an inbox request).
 * @param showLinkWarnings True on the project tier, where a request can be linked to a Pain Point and have requesters.
 */
export function requestColumns({
  scheme, models, titleExtra, codeCell, showLinkWarnings,
}: {
  scheme: ScoringScheme | null;
  models: string[];
  titleExtra?: (r: EnhancementRequest) => ReactNode;
  codeCell: (r: EnhancementRequest) => ReactNode;
  showLinkWarnings: boolean;
}): DirectoryColumn<EnhancementRequest>[] {
  const modelLabel = (key: string) => scheme?.models.find((m) => m.key === key)?.label ?? key;
  // A model's label spells out its axes ("ICE (Impact × Confidence × Ease)"); the header keeps the name and the tooltip the rest.
  const shortLabel = (key: string) => modelLabel(key).split(" (")[0];
  const settled = (r: EnhancementRequest) => r.status === "declined" || r.status === "duplicate";
  return [
    { key: "code", label: "Code", render: codeCell },
    {
      key: "title", label: "Title",
      render: (r) => (
        <>
          {r.title}
          {titleExtra?.(r)}
          {r.merged_into && <Badge tone="muted" className="badge-after">Duplicate of {r.merged_into.unique_code}</Badge>}
          {showLinkWarnings && r.pain_point_count === 0 && !settled(r) && (
            <Badge tone="warning" className="badge-after" title="This is a solution with no stated problem. Link a Pain Point it addresses.">
              No Pain Point
            </Badge>
          )}
          {showLinkWarnings && r.loop_open_count > 0 && (
            <Badge tone="warning" className="badge-after" title="Requesters who have not been told the outcome">
              {r.loop_open_count} to tell
            </Badge>
          )}
        </>
      ),
    },
    { key: "status", label: "Status", render: (r) => <Badge tone={REQUEST_STATUS_TONE[r.status]}>{REQUEST_STATUS_LABEL[r.status]}</Badge> },
    ...(showLinkWarnings ? [{ key: "demand", label: "Demand", sortable: true, render: (r: EnhancementRequest) => demandText(r) }] : []),
    ...models.map((key, index) => ({
      key: index === 0 ? "score" : `score:${key}`,
      label: models.length > 1 ? <span title={modelLabel(key)}>Score ({shortLabel(key)})</span> : "Score",
      sortable: index === 0, render: (r: EnhancementRequest) => <RequestScoreBadge score={r.scores[key]} />,
    })),
    { key: "owner", label: "Owner", render: (r) => (r.owner ? <PrincipalBadge principal={r.owner} /> : "–") },
  ];
}
