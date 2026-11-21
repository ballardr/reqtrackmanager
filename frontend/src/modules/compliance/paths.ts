/**
 * Module: modules/compliance/paths
 *
 * URL builders for the Compliance module's own pages, shared by the screens that link to them and by
 * `module.ts`'s `artefactPaths` (so a search hit or a Links-panel row opens the same page a list row does).
 */

/** The project's Compliance page; `tab` opens it on that tab (`evidence`, `outstanding`). */
export function projectCompliancePath(projectId: string, tab?: "standards" | "evidence" | "outstanding"): string {
  const base = `/projects/${projectId}/modules/compliance`;
  return tab ? `${base}?tab=${tab}` : base;
}

/** One piece of evidence's detail page. */
export function evidencePath(projectId: string, evidenceId: string): string {
  return `/projects/${projectId}/modules/compliance/evidence/${evidenceId}`;
}

/** The views of the Standards page: the standards list and the two organisation-wide status tabs. */
export type StandardsView = "standards" | "by-standard" | "outstanding";

/** Matches the address of a status tab (`/standards/by-standard`, `/standards/outstanding`). */
export const STANDARDS_STATUS_PATH = /^\/standards\/(by-standard|outstanding)\/?$/;

/** Matches a standard's own workspace (`/standards/:standardId...`), never the settings or a status tab; capture 1 is the standard id. */
export const STANDARD_WORKSPACE_PATH = /^\/standards\/(?!(?:settings|by-standard|outstanding)(?:\/|$))([^/]+)/;

/**
 * The address of a Standards page view.
 *
 * @param view The view.
 * @param params Query parameters (a status tab reads `org` and its own filters from them); empty values are left out.
 */
export function standardsViewPath(view: StandardsView, params: Record<string, string | undefined> = {}): string {
  const base = view === "standards" ? "/standards" : `/standards/${view}`;
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value);
  const text = query.toString();
  return text ? `${base}?${text}` : base;
}
