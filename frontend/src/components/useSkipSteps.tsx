/**
 * Module: components/useSkipSteps
 *
 * Skipping steps on one record, as the pieces a record page draws: a row **Skip steps…** for the record's actions menu
 * and the dialog it opens (the later step to move to, a required reason, `FormActions` in the dialog header).
 *
 * Responsibilities:
 * - Offer the row only where the project's effective lifecycle lists a skip from the record's state
 *   (`EffectiveLifecycle.skipTargets`), so the row is absent, never disabled, when skipping is off or has nowhere to go.
 * - Hand the chosen target and reason to the page's `move`, which makes the target's own move request through
 *   `withLifecycleSkip` so that move keeps its own permission, and report the outcome as a toast.
 *
 * Design decisions: the row never replaces Promote, the track's one primary move; the server stays the authority (a
 * person without the right to enter a skipped step is refused there and sees the server's message).
 */
import { useState, type ReactNode } from "react";

import { toErrorMessage, useToast } from "../context/ToastContext";
import type { EffectiveLifecycle } from "../hooks/useProjectLifecycle";
import { useStrings } from "../context/TerminologyContext";
import type { ActionMenuItem } from "./ActionMenu";
import type { LifecycleSkip } from "./LifecycleTrack";
import { SkipStepsDialog } from "./SkipStepsDialog";

/**
 * @param lifecycle The record type's effective lifecycle in the record's project.
 * @param current The record's current state.
 * @param labels The type's status labels (`*_STATUS_LABEL`).
 * @param noun The record type's singular name for the title, e.g. "Decision".
 * @param move Moves the record to `target` with `reason`: the page's own move request for that target, run through
 *   `withLifecycleSkip`. It resolves with the updated record and rejects with the server's refusal.
 * @param onMoved Receives the updated record (the page stores it).
 * @param hidden True when the record cannot be changed from this page (an organisation record opened in a project).
 * @returns `menuRow` for the record header's `actions` (`false` when there is no skip to offer), `track` for the
 *   lifecycle track's `skip` prop (the steps drawn in bold, each opening the dialog for it; `undefined` when none)
 *   and `dialog`, which the page renders anywhere inside its tree.
 */
export function useSkipSteps<T>({
  lifecycle, current, labels, noun, move, onMoved, hidden = false,
}: {
  lifecycle: EffectiveLifecycle;
  current: string;
  labels: Readonly<Record<string, string>>;
  noun: string;
  move: (target: string, reason: string) => Promise<T>;
  onMoved: (updated: T) => void;
  hidden?: boolean;
}): { menuRow: ActionMenuItem | false; track: LifecycleSkip | undefined; dialog: ReactNode } {
  const strings = useStrings();
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);
  const [initial, setInitial] = useState<string | undefined>(undefined);
  const targets = hidden ? [] : lifecycle.skipTargets(current);
  const label = (key: string) => labels[key] ?? key;

  const menuRow: ActionMenuItem | false = targets.length > 0 && { label: strings.lifecycle.skipSteps, onSelect: () => { setInitial(undefined); setOpen(true); } };
  const track: LifecycleSkip | undefined = targets.length > 0
    ? { to: targets.map((t) => t.target), onSkip: (to) => { setInitial(to); setOpen(true); } }
    : undefined;
  const dialog = open && targets.length > 0 ? (
    <SkipStepsDialog
      noun={noun} initialTarget={initial}
      options={targets.map(({ target, passed }) => ({ value: target, label: strings.lifecycle.skipOption(label(target), passed.map(label)) }))}
      onClose={() => setOpen(false)}
      onSubmit={async (target, reason) => {
        setOpen(false);
        try {
          onMoved(await move(target, reason));
          showToast(strings.lifecycle.skipped(noun, label(target)));
        } catch (err) {
          showToast(toErrorMessage(err, strings.common.error), "error");
        }
      }}
    />
  ) : null;
  return { menuRow, track, dialog };
}
