/**
 * Module: modules/compliance/ApplicabilityBadge
 *
 * The applicability indicator that clearly distinguishes explicitly set applicability, applicability inherited from a parent
 * and an overridden inherited value, as one shared component so `ApplicabilityTree`'s rows and `RequirementAssessmentPanel`'s
 * header render the same three treatments. EXPLICIT (a user decision, or nothing decided with no conflicting ancestor, which
 * render identically per the backend's `ComplianceApplicabilitySource`) is a plain badge; INHERITED is muted and italic with an
 * explanatory `title`; OVERRIDDEN is in the warning colour with its own `title`. The treatments differ visually, not only in
 * label, so the distinction survives a quick scan.
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
