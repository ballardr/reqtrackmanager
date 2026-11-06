/**
 * Module: modules/product_feedback/useScorePreview
 *
 * The live scores a request form shows while levels are being chosen. The server derives them (the same code
 * that scores a saved request, so the form can never disagree with the list), so this hook only asks: it waits
 * a moment after the last change, drops a response that a newer choice has overtaken, and keeps the previous
 * scores on screen while the next arrive so the panel does not flicker.
 */
import { useState } from "react";

import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useRequestSequence } from "../../hooks/useRequestSequence";
import type { LevelDraft } from "./requestLevels";
import type { ScorePreview } from "./types";

/** How long after the last choice the server is asked. */
export const SCORE_PREVIEW_DEBOUNCE_MS = 250;

/** What the form shows: the latest answer, whether another is on its way, and whether the last ask failed. */
export interface ScorePreviewState {
  preview: ScorePreview | null;
  loading: boolean;
  failed: boolean;
}

/**
 * @param fetchPreview Asks the server to score the levels (`previewScores` of the tier's API, bound to its id).
 * @param levels The levels chosen so far (a null is an axis not scored).
 * @param requestId The request being edited, so its weighted demand feeds the derived Demand axis.
 * @returns The preview state; it refreshes whenever the levels or the request change.
 */
export function useScorePreview(
  fetchPreview: (levels: LevelDraft, requestId?: string) => Promise<ScorePreview>, levels: LevelDraft, requestId?: string,
): ScorePreviewState {
  const [state, setState] = useState<ScorePreviewState>({ preview: null, loading: true, failed: false });
  const begin = useRequestSequence();
  useLoadOnChange(async () => {
    const isLatest = begin();
    setState((prev) => ({ ...prev, loading: true }));
    await new Promise((resolve) => setTimeout(resolve, SCORE_PREVIEW_DEBOUNCE_MS));
    if (!isLatest()) return;
    try {
      const preview = await fetchPreview(levels, requestId);
      if (isLatest()) setState({ preview, loading: false, failed: false });
    } catch {
      if (isLatest()) setState((prev) => ({ ...prev, loading: false, failed: true }));
    }
  }, [levels, requestId]);
  return state;
}
