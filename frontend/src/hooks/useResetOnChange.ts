/**
 * Module: hooks/useResetOnChange
 *
 * Runs `reset` (typically a few state setters) in the render in which the
 * listed values changed, so the new render already shows the reset state.
 * The alternative, an effect that calls the setters, paints one render with
 * stale state first and then renders again (the cascading render the
 * `react-hooks/set-state-in-effect` rule exists to catch); setting state
 * during render of the same component, guarded by a change check, is the
 * pattern React documents for "adjusting state when a prop changes".
 *
 * Does nothing on the first render unless `runOnMount` is set (state already
 * holds its initial value); with it, `reset` also runs in the first render, for
 * state that must be derived from the starting values (a deep link in the URL).
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
