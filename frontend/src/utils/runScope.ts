/**
 * Module: utils/runScope
 *
 * Reads which projects a layout may run for from its text view.
 *
 * Responsibilities: tell the designer's preview and the page setup the layout's `run_scope` (any number of projects,
 * exactly one, or one with its child projects), so the preview offers the right project picker. The server enforces
 * the rule on every run; this only shapes the form.
 */

/** Which projects a layout runs for: any number, exactly one, or one with its readable child projects merged in. */
export type RunScope = "any" | "one" | "one_and_children";

/** The words of the `@layout` line, by scope. */
export const RUN_SCOPE_WORDS: Record<RunScope, string> = { any: "anyprojects", one: "oneproject", one_and_children: "projecttree" };

/** The scope an `@layout` line's words state, `undefined` when it states none (which means any). */
export function runScopeOfWords(words: string[]): RunScope | undefined {
  return (Object.keys(RUN_SCOPE_WORDS) as RunScope[]).find((scope) => words.includes(RUN_SCOPE_WORDS[scope]));
}

/** The scope the draft's `@layout` line states; `any` when it states none. */
export function readRunScope(text: string): RunScope {
  return runScopeOfWords((text.split("\n", 1)[0] ?? "").split(/\s+/)) ?? "any";
}

/** A comma-separated `project_ids` run value as a list. */
export function projectIdList(value: unknown): string[] {
  return typeof value === "string" ? value.split(",").filter(Boolean) : [];
}
