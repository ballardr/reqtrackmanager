/**
 * Module: hooks/useResetOnChange
 *
 * Runs `reset` (typically a few state setters) in the render in which the listed values changed, so the new
 * render already shows the reset state. An effect calling the setters would paint stale state first and render
 * again (the cascading render `react-hooks/set-state-in-effect` catches); setting state during render, guarded by a
 * change check, is React's documented "adjusting state when a prop changes" pattern.
 *
 * Does nothing on the first render unless `runOnMount` is set; then `reset` also runs in the first render, for
 * state derived from the starting values (a deep link in the URL).
 */
import { useState } from "react";

/**
 * @param deps Plain values (ids, filters) whose change triggers the reset; compared by their JSON form.
 * @param reset Resets the owning component's state. Must only set state of the component that calls this hook.
 * @param options `runOnMount`: also run `reset` in the first render.
 */
export function useResetOnChange(deps: readonly unknown[], reset: () => void, options: { runOnMount?: boolean } = {}): void {
  const key = JSON.stringify(deps);
  const [seen, setSeen] = useState<string | null>(options.runOnMount ? null : key);
  if (seen !== key) {
    setSeen(key);
    reset();
  }
}
