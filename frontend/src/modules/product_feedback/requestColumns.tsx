/**
 * Module: modules/product_feedback/requestColumns
 *
 * The table columns the project list and the organisation inbox share. Demand sits beside the score, never inside it.
 * A request with no Pain Point carries a warning in the optional Pain Points column (a solution with no stated problem), never a block.
 */
import type { ReactNode } from "react";

import type { ScoringScheme } from "../../api/scoring";
import { Badge } from "../../components/Badge";
import type { DirectoryColumn } from "../../components/DirectoryTable";
import { PrincipalBadge } from "../../components/PrincipalBadge";
import { RequestScoreBadge } from "./RequestScoreBadge";
import { modelShortName } from "./requestLevels";
import { demandText } from "./requestListState";
import { REQUEST_STATUS_LABEL, REQUEST_STATUS_TONE } from "./types";
import type { EnhancementRequest } from "./types";

/** Codes, statuses, demand and scores are short and read as one unit, so they never wrap; the title takes the slack. */
const NO_WRAP = { whiteSpace: "nowrap" } as const;

/** A past instant (a UTC timestamp from the API) in the viewer's own timezone, date and time. */
const instantText = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/**
 * The columns of a request list.
 *
 * @param scheme The scoring scheme in effect (model labels for the score columns).
 * @param models The model keys to show a score column for.
 * @param shown The ids of the optional columns the person has chosen (`status`, `demand`, `pain_points`, `owner`, `created`, `updated`); the code and title are always on.
 * @param titleExtra Extra content after a row's title (the project list adds the scope label).
 * @param codeCell How a row's code is shown (a project code, or the organisation-qualified one for an inbox request).
 * @param showLinkWarnings True on the project tier, where a request can be linked to a Pain Point and have requesters.
 */
export function requestColumns({
  scheme, models, shown, titleExtra, codeCell, showLinkWarnings,
}: {
  scheme: ScoringScheme | null;
  models: string[];
  shown: readonly string[];
  titleExtra?: (r: EnhancementRequest) => ReactNode;
  codeCell: (r: EnhancementRequest) => ReactNode;
  showLinkWarnings: boolean;
}): DirectoryColumn<EnhancementRequest>[] {
  const modelLabel = (key: string) => scheme?.models.find((m) => m.key === key)?.label ?? key;
  // A model's label spells out its axes ("ICE (Impact × Confidence × Ease)"); the header keeps the name and the tooltip the rest.
  const shortLabel = (key: string) => modelShortName(modelLabel(key));
  const settled = (r: EnhancementRequest) => r.status === "declined" || r.status === "duplicate";
  // A request that addresses no Pain Point is a solution with no stated problem: flagged, never blocked, except where
  // the request is settled (declined or a duplicate) and the gap no longer matters.
  const painPointCell = (r: EnhancementRequest) => (
    r.pain_point_count > 0 ? r.pain_point_count
      : settled(r) ? <span className="text-muted">None</span>
        : <Badge tone="warning" title="A solution with no stated problem. Link the Pain Point it addresses.">None</Badge>
  );
  return [
    { key: "code", label: "Code", render: (r) => <span style={NO_WRAP}>{codeCell(r)}</span> },
    {
      key: "title", label: "Title",
      render: (r) => (
        <>
          {r.title}
          {titleExtra?.(r)}
          {r.merged_into && <Badge tone="muted" className="badge-after">Duplicate of {r.merged_into.unique_code}</Badge>}
          {showLinkWarnings && r.loop_open_count > 0 && (
            <Badge tone="warning" className="badge-after" title="Requesters who have not been told the outcome">
              {r.loop_open_count} to tell
            </Badge>
          )}
        </>
      ),
    },
    ...(shown.includes("status") ? [{
      key: "status", label: "Status",
      render: (r: EnhancementRequest) => <span style={NO_WRAP}><Badge tone={REQUEST_STATUS_TONE[r.status]}>{REQUEST_STATUS_LABEL[r.status]}</Badge></span>,
    }] : []),
    ...(showLinkWarnings && shown.includes("demand") ? [{ key: "demand", label: "Demand", sortable: true, render: (r: EnhancementRequest) => <span style={NO_WRAP}>{demandText(r)}</span> }] : []),
    ...(showLinkWarnings && shown.includes("pain_points") ? [{ key: "pain_points", label: "Pain Points", sortable: true, render: (r: EnhancementRequest) => <span style={NO_WRAP}>{painPointCell(r)}</span> }] : []),
    ...models.map((key, index) => ({
      key: index === 0 ? "score" : `score:${key}`,
      label: models.length > 1 ? <span title={modelLabel(key)}>Score ({shortLabel(key)})</span> : "Score",
      sortable: index === 0, render: (r: EnhancementRequest) => <span style={NO_WRAP}><RequestScoreBadge score={r.scores[key]} /></span>,
    })),
    ...(shown.includes("owner") ? [{ key: "owner", label: "Owner", render: (r: EnhancementRequest) => (r.owner ? <PrincipalBadge principal={r.owner} /> : "–") }] : []),
    ...(shown.includes("created") ? [{ key: "created", label: "Created", sortable: true, render: (r: EnhancementRequest) => <span style={NO_WRAP}>{instantText(r.created_at)}</span> }] : []),
    ...(shown.includes("updated") ? [{ key: "updated", label: "Last updated", sortable: true, render: (r: EnhancementRequest) => <span style={NO_WRAP}>{instantText(r.updated_at)}</span> }] : []),
  ];
}
