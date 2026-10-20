/**
 * Module: modules/compliance/ApplicabilityBadge
 *
 * §9's own explicit, non-optional UI requirement — "The UI must clearly
 * distinguish: Explicitly set applicability, Applicability inherited from
 * a parent, An overridden inherited value" — as one shared component, so
 * `ApplicabilityTree`'s tree rows and `RequirementAssessmentPanel`'s detail
 * header render the exact same three visual treatments rather than two
 * independently-drifting copies of the same logic. EXPLICIT (a real user
 * decision, or nothing decided and no ancestor conflicts — both render
 * identically per `ComplianceApplicabilitySource`'s own backend docstring)
 * is a plain, undecorated badge; INHERITED is greyed/italic with an
 * explanatory `title`; OVERRIDDEN is in the warning colour with its own
 * explanatory `title` — three genuinely distinct treatments, not just three
 * label strings, so the distinction survives a quick scan, not just a
 * hover.
 */
import { COMPLIANCE_APPLICABILITY_LABEL, type ProjectComplianceRequirement } from "./types";
import { Badge } from "../../components/Badge";

export function ApplicabilityBadge({ pcr }: { pcr: ProjectComplianceRequirement }) {
  const label = COMPLIANCE_APPLICABILITY_LABEL[pcr.effective_applicability];
  if (pcr.applicability_source === "inherited") {
    return (
      <Badge
        tone="muted"
        title="Inherited: no explicit decision on this requirement — a parent requirement is Not Applicable."
        style={{ fontStyle: "italic" }}>
        {label} (inherited)
      </Badge>
    );
  }
  if (pcr.applicability_source === "overridden") {
    return (
      <Badge
        tone="warning"
        title="Overridden: explicitly marked Applicable despite a parent requirement being Not Applicable."
        style={{ fontWeight: 600 }}>
        {label} (overridden)
      </Badge>
    );
  }
  return <Badge>{label}</Badge>;
}
