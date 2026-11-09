/**
 * Module: utils/clarity
 *
 * Optional Microsoft Clarity session analytics for a demonstration deployment.
 *
 * Responsibilities:
 * - Validate the project identifier supplied at container start (`window.__ENV__.CLARITY_PROJECT_ID`).
 * - Insert Clarity's loader script once, only when a valid identifier is present.
 *
 * Design decisions:
 * - Off unless the operator sets `DEMO_CLARITY_PROJECT_ID`; a production deployment never sets it, so no
 *   third-party script loads and nothing is sent to a vendor.
 * - The identifier is checked against a strict pattern before it is placed in a script URL, so a malformed
 *   value can never inject script or change the host.
 * - What Clarity records and masks is configured in the operator's own Clarity project, not here.
 *
 * External dependencies: Microsoft Clarity (`https://www.clarity.ms/tag/<id>`), loaded only when enabled.
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
 * @returns True when the script was added by this call.
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
