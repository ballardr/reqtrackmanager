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
