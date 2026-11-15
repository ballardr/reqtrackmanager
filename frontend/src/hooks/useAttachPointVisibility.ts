/**
 * Module: hooks/useAttachPointVisibility
 *
 * The person's choice of when the shared graph canvas draws a box's attach points, and the canvas prop that applies it.
 *
 * Responsibilities:
 * - Read and write one choice, "Always show attach points" (off: only near the pointer), for every canvas editor.
 * - Give the prop `GraphCanvas` takes (`attachPointVisibility`).
 *
 * Design decisions:
 * - Kept in the user's `ui_preferences` (`useUiPreference`), so it follows the person to another browser or device, unlike
 *   Snap to grid, which is local to one browser. It is a display preference only: never part of a diagram, never applied to
 *   an export and invisible to other people. An unknown stored value reads as the default.
 * - Near the pointer by default, so a drawing is not covered in dots until a person asks for them.
 *
 * Dependencies: `useUiPreference`.
 */
import type { GraphCanvasProps } from "../components/GraphCanvas";
import { useUiPreference } from "./useUiPreference";

/** The `ui_preferences` key holding the choice: "always" or "near". */
export const ATTACH_POINTS_PREFERENCE = "canvas_attach_points";

/**
 * @returns `always` (whether points are always drawn), `setAlways` (stores a new choice) and `canvasProps` (spread onto `GraphCanvas`).
 */
export function useAttachPointVisibility(): {
  always: boolean;
  setAlways: (next: boolean) => void;
  canvasProps: Pick<GraphCanvasProps, "attachPointVisibility">;
} {
  const [stored, setStored] = useUiPreference<string>(ATTACH_POINTS_PREFERENCE, "near");
  const always = stored === "always";
  return {
    always,
    setAlways: (next) => setStored(next ? "always" : "near"),
    canvasProps: { attachPointVisibility: always ? "always" : "near" },
  };
}
