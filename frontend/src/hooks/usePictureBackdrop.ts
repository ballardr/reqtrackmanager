import { useUiPreference } from "./useUiPreference";

/** What a drawn picture sits on: a checkerboard (the default), a light page or a dark page. */
export type PictureBackdrop = "checkerboard" | "light" | "dark";

export const PICTURE_BACKDROPS: PictureBackdrop[] = ["checkerboard", "light", "dark"];
const PREFERENCE_KEY = "picture_backdrop";

/**
 * Reads and writes the person's picture backdrop, one display preference read by every `PictureImage`.
 *
 * Returns: the current backdrop (a stale or hand-edited stored value falls back to the checkerboard) and its setter.
 */
export function usePictureBackdrop(): [PictureBackdrop, (backdrop: PictureBackdrop) => void] {
  const [stored, setStored] = useUiPreference<string>(PREFERENCE_KEY, "checkerboard");
  const backdrop = PICTURE_BACKDROPS.find((b) => b === stored) ?? "checkerboard";
  return [backdrop, setStored];
}
