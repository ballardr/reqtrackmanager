/**
 * Module: modules/architecture/StateMachineFindings
 *
 * The modelling findings of a state machine diagram, beside the Change status menu: how many errors and warnings there are
 * and, in a list, each one with the state or transition it concerns. The findings come from the server's one checking
 * function (`state_machine_checks`); nothing here works one out.
 *
 * Responsibilities:
 * - Show the counts as badges (an error blocks activation, a warning never does) and the list, each row selecting its subject
 *   on the canvas when it names one.
 * - Say plainly when there is nothing to report, since an empty list is the answer the person is looking for.
 */
import { Badge } from "../../components/Badge";
import { DetailCard } from "../../components/DetailCard";
import { FieldHelp } from "../../components/FieldHelp";
import { ARCHITECTURE_HELP } from "./help";
import { FINDING_SEVERITY_LABEL, type StateMachineFinding } from "./types";

/**
 * @param findings The diagram's findings.
 * @param onSelect Called with a finding's subject code when its row is chosen (a state code; never empty).
 * @param subjectLabel How a subject code is shown on its button (the record-code display rule); the code itself by default.
 */
export function StateMachineFindings({
  findings, onSelect, subjectLabel = (code) => code,
}: {
  findings: readonly StateMachineFinding[];
  onSelect?: (subject: string) => void;
  subjectLabel?: (code: string) => string;
}) {
  const errors = findings.filter((f) => f.severity === "error").length;
  const warnings = findings.length - errors;
  return (
    <DetailCard
      heading="Findings"
      action={<FieldHelp label="Findings" help={ARCHITECTURE_HELP.stateMachineFindings} />}
    >
      <div className="row" style={{ gap: "var(--space-2)" }}>
        <Badge tone={errors > 0 ? "danger" : "muted"}>{errors} {errors === 1 ? "error" : "errors"}</Badge>
        <Badge tone={warnings > 0 ? "warning" : "muted"}>{warnings} {warnings === 1 ? "warning" : "warnings"}</Badge>
      </div>
      {findings.length === 0 ? (
        <p className="text-muted">No findings.</p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {findings.map((f, index) => (
            <li key={`${f.code}:${f.subject}:${index}`} className="row" style={{ gap: "var(--space-2)", alignItems: "baseline" }}>
              <Badge tone={f.severity === "error" ? "danger" : "warning"}>{FINDING_SEVERITY_LABEL[f.severity]}</Badge>
              <span>
                {f.subject && onSelect ? (
                  <button type="button" className="btn btn-sm" onClick={() => onSelect(f.subject)}>{subjectLabel(f.subject)}</button>
                ) : subjectLabel(f.subject)}
                {" "}{f.message}
              </span>
            </li>
          ))}
        </ul>
      )}
    </DetailCard>
  );
}
