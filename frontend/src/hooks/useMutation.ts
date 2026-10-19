/**
 * Module: hooks/useMutation
 *
 * One way to run a state-changing API call from a handler (docs/ux-style-guide.md, Principle 7: every
 * mutation ends with feedback): it awaits the call, shows a success Toast, and turns a failure into an
 * error Toast (the server's own message when it sent one) instead of an unhandled rejection.
 */
import { useCallback, useContext } from "react";

import { toErrorMessage, useToast } from "../context/ToastContext";
import { ProjectContext } from "../context/ProjectContextValue";
import { applyTerminology } from "../i18n/terminology";
import { t } from "../i18n/strings";

const strings = t();

export type MutationVerb = keyof typeof strings.mutation.past;

/** What to say when the call ends, in full. */
export type MutationMessages = { success?: string; failure: string };

/**
 * Returns `run(action, verb, noun)` or `run(action, { success, failure })`.
 *
 * `run` resolves to `true` after the call succeeds (its success Toast is shown) and to `false` after it
 * fails (its error Toast is shown); it never rejects. Callers continue with their follow-up work only
 * on `true`, e.g. `if (await run(() => api.post(url), "add", "{stage}")) reload();`.
 *
 * A verb and noun generate both messages ("Stage added." / "Could not add the stage."). Any message may
 * carry a terminology token (`{stage}`, `{requirement}`), resolved for the current project. Give only
 * `{ failure }` for a one-tap toggle or reorder whose new state on screen is the feedback.
 */
export function useMutation() {
  const { showToast } = useToast();
  const { terminology } = useContext(ProjectContext);
  return useCallback(
    async (action: () => Promise<unknown>, verbOrMessages: MutationVerb | MutationMessages, noun?: string): Promise<boolean> => {
      const messages: MutationMessages =
        typeof verbOrMessages === "string"
          ? {
              success: strings.mutation.success(noun ?? "", strings.mutation.past[verbOrMessages]),
              failure: strings.mutation.failure(verbOrMessages, noun ?? ""),
            }
          : verbOrMessages;
      try {
        await action();
      } catch (err) {
        showToast(toErrorMessage(err, applyTerminology(messages.failure, terminology)), "error");
        return false;
      }
      if (messages.success) showToast(applyTerminology(messages.success, terminology));
      return true;
    },
    [showToast, terminology]
  );
}
