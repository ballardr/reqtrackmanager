/**
 * Module: components/LifecycleTrack
 *
 * The one display of where a record is in its life: a full-width row of chevron-shaped steps (earlier steps tinted,
 * the current step in the primary colour, later steps plain) and the single forward move, Promote. `RecordHeader`
 * draws it for every record with states (`lifecycle` prop), so no page draws its own row of transition buttons.
 *
 * Responsibilities:
 * - Show the main path as ordered steps; a record in a branch state (Rejected, Withdrawn, Retired) shows that state
 *   as one extra end step (`offPath`), highlighted, and never pretends the lifecycle is a line.
 * - Mark a locked step with a padlock whose tooltip gives the reason, and mark the next step with a padlock when the
 *   person may not promote the record (`promote.blockedReason`).
 * - Offer Promote in two places that run the same move: the next step opens a popover with the Promote button, and
 *   `RecordHeader` adds Promote as the first row of the record's actions menu. The page owns what a Promote does
 *   (its own confirmation or approval dialog), so the track never skips an approval gate.
 * - At a narrow width collapse to the current step with its position and open the full track in a popover.
 *
 * Design decisions: colour is never the only signal (`aria-current="step"`, a text state for assistive technology,
 * the padlock); tints are theme tokens (`styles/theme.css`, `.lifecycle-step`); the last step has a flat end because
 * nothing follows it.
 *
 * External dependencies: `Tooltip`, `Popover`, `CellText`, `strings.lifecycle`.
 */
import { ChevronDown, Lock } from "lucide-react";
import { useLayoutEffect, useRef, useState } from "react";

import { useStrings } from "../context/TerminologyContext";
import { CellText } from "./CellText";
import { Popover } from "./Popover";
import { Tooltip } from "./Tooltip";
import { trackSteps, type StepState } from "./lifecycleSteps";

/** One step of a lifecycle. */
export interface LifecycleStep {
  /** Stable identity of the step (the status value). */
  key: string;
  /** Formal label shown in the step. */
  label: string;
  /** What the state means, shown as the step's tooltip. */
  description?: string;
  /** The record cannot be edited directly while it is in this step. */
  locked?: boolean;
  /** Why it is locked; the padlock's tooltip ("use a change request to modify"). */
  lockedReason?: string;
}

/**
 * The next forward move. A person who may promote gets `onPromote`; a person who may not gets `blockedReason`
 * (the permission the move needs) and the step shows a padlock instead of a control.
 */
export type LifecyclePromote =
  | { to: string; onPromote: () => void; blockedReason?: undefined }
  | { to: string; onPromote?: undefined; blockedReason: string };

/** What a page passes to `RecordHeader`'s `lifecycle` prop and what the track draws. */
export interface LifecycleTrackProps {
  /** The main path in order. */
  steps: LifecycleStep[];
  /** Key of the current step: one of `steps`, or `offPath.key`. */
  current: string;
  /** A branch state (Rejected, Withdrawn, Retired) drawn as one extra end step while it is current. `after` is the main step the record had reached. */
  offPath?: LifecycleStep & { after?: string };
  /** The next forward move; omit when no forward move exists from the current state. */
  promote?: LifecyclePromote;
}

/** Text for assistive technology that carries the state colour alone would. */
function stateText(strings: ReturnType<typeof useStrings>, state: StepState): string {
  return state === "done" ? strings.lifecycle.done : state === "current" ? strings.lifecycle.current : strings.lifecycle.later;
}

function StepBody({ step, state, lockReason }: { step: LifecycleStep; state: StepState; lockReason?: string }) {
  const strings = useStrings();
  return (
    <>
      <span className="lifecycle-step__fill" aria-hidden="true" />
      <span className="lifecycle-step__content">
        <span className="lifecycle-step__label"><CellText>{step.label}</CellText></span>
        {lockReason && (
          <Tooltip label={lockReason} wrap>
            <span className="lifecycle-step__lock" role="img" aria-label={lockReason}><Lock size={13} /></span>
          </Tooltip>
        )}
        <span className="sr-only">{`, ${stateText(strings, state)}`}</span>
      </span>
    </>
  );
}

/**
 * The chevron row. The step `promote.to` is a button that opens the Promote popover when `interactive`.
 */
function Steps({ steps, current, offPath, promote, interactive }: LifecycleTrackProps & { interactive: boolean }) {
  const strings = useStrings();
  const drawn = trackSteps(steps, current, offPath);
  const targetRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  return (
    <ol className="lifecycle-track__steps" aria-label={strings.lifecycle.label} data-stress-row>
      {drawn.map(({ step, state }, i) => {
        const classes = [
          "lifecycle-step", `lifecycle-step--${state}`,
          i === 0 ? "lifecycle-step--first" : "", i === drawn.length - 1 ? "lifecycle-step--last" : "",
          step.key === offPath?.key ? "lifecycle-step--branch" : "",
          interactive && promote?.onPromote && promote.to === step.key && state !== "current" ? "lifecycle-step--next" : "",
        ].filter(Boolean).join(" ");
        const isTarget = !!promote && promote.to === step.key && state !== "current";
        const lockReason = [
          step.locked ? step.lockedReason ?? strings.lifecycle.locked : undefined,
          isTarget ? promote.blockedReason : undefined,
        ].filter(Boolean).join("\n") || undefined;
        const canPress = interactive && isTarget && !!promote.onPromote;
        const tip = [step.label, step.description].filter(Boolean).join("\n");
        return (
          <li key={step.key} className={classes} aria-current={state === "current" ? "step" : undefined}>
            <Tooltip label={tip} wrap disabled={!step.description} className="lifecycle-step__tip">
              {canPress ? (
                <button
                  ref={targetRef} type="button" className="lifecycle-step__control" aria-haspopup="dialog" aria-expanded={open}
                  aria-label={strings.lifecycle.nextStep(step.label)} onClick={() => setOpen((o) => !o)}
                >
                  <StepBody step={step} state={state} lockReason={lockReason} />
                </button>
              ) : (
                <span className="lifecycle-step__control"><StepBody step={step} state={state} lockReason={lockReason} /></span>
              )}
            </Tooltip>
            {canPress && open && (
              <Popover anchorRef={targetRef} onClose={() => setOpen(false)} title={strings.lifecycle.promoteTo(step.label)} fit>
                <div className="stack" style={{ gap: "var(--space-3)" }}>
                  {step.description && <p className="text-muted" style={{ margin: 0 }}>{step.description}</p>}
                  <div className="row" style={{ justifyContent: "flex-end" }}>
                    <button type="button" className="btn btn-primary" onClick={() => { setOpen(false); promote.onPromote?.(); }}>
                      {strings.lifecycle.promoteTo(step.label)}
                    </button>
                  </div>
                </div>
              </Popover>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * The lifecycle track.
 *
 * @param props See `LifecycleTrackProps`.
 * @returns The full-width track; collapsed to the current step with a popover when it does not fit its container.
 */
export function LifecycleTrack(props: LifecycleTrackProps) {
  const strings = useStrings();
  const { steps, current, offPath, promote } = props;
  const wrapRef = useRef<HTMLDivElement>(null);
  const fullRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [compact, setCompact] = useState(false);
  const [open, setOpen] = useState(false);

  // The full track is always laid out (hidden while collapsed) so its natural width is known; the track collapses
  // when the container is narrower than that.
  useLayoutEffect(() => {
    const wrap = wrapRef.current;
    const full = fullRef.current;
    if (!wrap || !full) return;
    function measure() {
      if (!wrap || !full) return;
      setCompact(full.scrollWidth > wrap.clientWidth + 1);
    }
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [steps, current, offPath, promote?.to]);

  const drawn = trackSteps(steps, current, offPath);
  const position = Math.max(0, drawn.findIndex((d) => d.state === "current"));
  const currentStep = drawn[position]?.step;

  return (
    <div className="lifecycle-track" ref={wrapRef}>
      <div
        className={`lifecycle-track__full${compact ? " lifecycle-track__full--hidden" : ""}`}
        ref={fullRef}
        // `inert` keeps a collapsed (hidden) copy out of the tab order and the accessibility tree.
        {...(compact ? { inert: true } : {})}
      >
        <Steps {...props} interactive={!compact} />
      </div>
      {compact && currentStep && (
        <>
          <button
            ref={triggerRef} type="button" className="btn lifecycle-track__compact" aria-expanded={open} aria-haspopup="dialog"
            onClick={() => setOpen((o) => !o)}
          >
            <span className="text-muted">{strings.lifecycle.position(position + 1, drawn.length)}</span>
            <CellText>{currentStep.label}</CellText>
            {currentStep.locked && <Lock size={13} aria-hidden="true" />}
            <ChevronDown size={14} aria-hidden="true" />
          </button>
          {open && (
            <Popover anchorRef={triggerRef} onClose={() => setOpen(false)} title={strings.lifecycle.label} fit>
              <div className="lifecycle-track__popover"><Steps {...props} interactive={false} /></div>
            </Popover>
          )}
        </>
      )}
    </div>
  );
}
