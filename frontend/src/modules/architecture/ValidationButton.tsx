/**
 * Module: modules/architecture/ValidationButton
 *
 * The toolbar button for a state machine diagram's validation: a count badge (the errors, or else the warnings, or none)
 * and a list, in a popover, of every error and warning with the state it concerns. The issues come from the server's one
 * checking function (`state_machine_checks`); nothing here works one out.
 *
 * Responsibilities:
 * - Show the count on the button so a problem is visible without opening anything (an error blocks activation, a warning
 *   never does).
 * - List each issue (its message already names the state by code), a row that concerns a state selecting it on the canvas;
 *   an issue about the whole diagram is plain text.
 * - Say plainly when there is nothing to report, since an empty list is the answer the person is looking for.
 *
 * Design decisions:
 * - The open state belongs to the page, so the Selection card's "N issues" link can open the list at that state
 *   (`focusSubject` marks its rows); the button only reports a press.
 * - The button is a small toolbar button with its help as a tooltip (docs/ux-style-guide.md, "Pattern: help on
 *   interactive elements"); its accessible name begins with the visible word (WCAG 2.5.3).
 * - Rows are the shared `menu-item` text rows, never bordered buttons ("Pattern: action menu").
 */
import { useId, useRef } from "react";

import { Badge } from "../../components/Badge";
import { Popover } from "../../components/Popover";
import { Tooltip } from "../../components/Tooltip";
import { ARCHITECTURE_HELP } from "./help";
import { type StateMachineValidationIssue, VALIDATION_SEVERITY_LABEL } from "./types";
import { countIssues, plural, VALIDATION_LABEL, validationName } from "./validationIssues";

/**
 * @param issues The diagram's validation issues, errors first.
 * @param open Whether the list is open.
 * @param onOpenChange Called with the new open state when the button is pressed or the list closes itself.
 * @param onSelect Called with an issue's subject (a state code; never empty) when its row is chosen.
 * @param focusSubject A subject whose rows are marked as current, for a list opened from that state's card.
 */
export function ValidationButton({
  issues, open, onOpenChange, onSelect, focusSubject = null,
}: {
  issues: readonly StateMachineValidationIssue[];
  open: boolean;
  onOpenChange: (next: boolean) => void;
  onSelect: (subject: string) => void;
  focusSubject?: string | null;
}) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const bubbleId = useId();
  const { errors, warnings } = countIssues(issues);
  const badge = errors > 0
    ? <Badge tone="danger">{errors}</Badge>
    : warnings > 0 ? <Badge tone="warning">{warnings}</Badge> : null;

  const trigger = (
    <button
      ref={triggerRef} type="button" className={`btn btn-sm${open ? " btn-marked" : ""}`} aria-label={validationName(errors, warnings)}
      aria-haspopup="dialog" aria-expanded={open} aria-describedby={bubbleId} onClick={() => onOpenChange(!open)}
    >
      {VALIDATION_LABEL}
      {badge}
    </button>
  );

  return (
    <>
      <Tooltip label={ARCHITECTURE_HELP.stateMachineValidation} wrap bubbleId={bubbleId}>{trigger}</Tooltip>
      {open && (
        <Popover anchorRef={triggerRef} fit title={VALIDATION_LABEL} onClose={() => onOpenChange(false)}>
          <div className="stack" role="group" aria-label="Validation issues" style={{ gap: "var(--space-2)", maxWidth: "32rem" }}>
            <div className="row" style={{ gap: "var(--space-2)" }}>
              <Badge tone={errors > 0 ? "danger" : "muted"}>{plural(errors, "error")}</Badge>
              <Badge tone={warnings > 0 ? "warning" : "muted"}>{plural(warnings, "warning")}</Badge>
            </div>
            {issues.length === 0 ? (
              <p className="text-muted" style={{ margin: 0 }}>Nothing to report.</p>
            ) : (
              <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
                {issues.map((issue, index) => {
                  const content = (
                    <>
                      <Badge tone={issue.severity === "error" ? "danger" : "warning"}>{VALIDATION_SEVERITY_LABEL[issue.severity]}</Badge>
                      <span>{issue.message}</span>
                    </>
                  );
                  const current = focusSubject !== null && issue.subject === focusSubject;
                  return (
                    <li key={`${issue.code}:${issue.subject}:${index}`}>
                      {issue.subject ? (
                        <button
                          type="button" className="menu-item" aria-current={current ? "true" : undefined}
                          style={current ? { fontWeight: 600 } : undefined}
                          onClick={() => { onSelect(issue.subject); onOpenChange(false); }}
                        >
                          {content}
                        </button>
                      ) : (
                        <div className="menu-item" style={{ cursor: "default" }}>{content}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </Popover>
      )}
    </>
  );
}
