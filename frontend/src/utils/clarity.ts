/**
 * Module: utils/clarity
 *
 * Optional Microsoft Clarity session analytics for a demonstration deployment.
 * Responsibilities: validate the project identifier supplied at container start
 * (`window.__ENV__.CLARITY_PROJECT_ID`) and insert Clarity's loader script once,
 * only when a valid identifier is present.
 * Design: off unless the operator sets `DEMO_CLARITY_PROJECT_ID`, so a
 * production deployment loads no third-party script. The identifier is checked
 * against a strict pattern before it is placed in a script URL, so a malformed
 * value cannot inject script or change the host. What Clarity records and masks
 * is configured in the operator's own Clarity project.
 * External dependencies: Microsoft Clarity (`https://www.clarity.ms/tag/<id>`).
 */

const PROJECT_ID_PATTERN = /^[A-Za-z0-9]{4,32}$/;
const SCRIPT_ATTRIBUTE = "data-clarity-project";

/**
 * Returns the Clarity project identifier when it is well formed.
 *
 * @param value The raw configured value.
 * @returns The identifier, or `null` when it is absent or malformed.
 */
export function validClarityProjectId(value: string | undefined | null): string | null {
  const trimmed = (value ?? "").trim();
  return PROJECT_ID_PATTERN.test(trimmed) ? trimmed : null;
}

/**
 * Loads Microsoft Clarity once when a valid project identifier is configured.
 *
 * @param projectId The raw configured identifier (`window.__ENV__?.CLARITY_PROJECT_ID`).
 * @param doc The document to add the script to.
 * @returns True when this call added the script.
 * @sideEffects Appends a `<script async>` element to the document head and defines `window.clarity`.
 */
export function loadClarity(projectId: string | undefined | null, doc: Document = document): boolean {
  const id = validClarityProjectId(projectId);
  if (id === null || doc.querySelector(`script[${SCRIPT_ATTRIBUTE}]`) !== null) return false;
  const win = doc.defaultView as (Window & { clarity?: ((...args: unknown[]) => void) & { q?: unknown[] } }) | null;
  if (win !== null && win.clarity === undefined) {
    const queue = (...args: unknown[]): void => {
      (queue as { q?: unknown[] }).q = (queue as { q?: unknown[] }).q ?? [];
      (queue as { q?: unknown[] }).q!.push(args);
    };
    win.clarity = queue;
  }
  const script = doc.createElement("script");
  script.async = true;
  script.src = `https://www.clarity.ms/tag/${id}`;
  script.setAttribute(SCRIPT_ATTRIBUTE, id);
  doc.head.appendChild(script);
  return true;
}
