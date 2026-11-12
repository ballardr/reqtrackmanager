/**
 * Module: modules/architecture/diagramExport
 *
 * The pieces of exporting a diagram that need no React: the file name of an export and the view-switch states a server
 * export is asked for.
 *
 * Design decisions:
 * - An export is the server's resolved document (SVG, Mermaid text) for the switch states on the page, so a file, a report
 *   and the screen show the same lines; a PNG is that SVG drawn in the browser.
 */
import type { DiagramToggle } from "./types";

/** The kinds of export the editor offers. */
export type DiagramExportKind = "png" | "svg" | "mermaid" | "copy-mermaid";

/** The switch states of a page, as a server export call names them. */
export interface ToggleStates {
  on: string[];
  off: string[];
}

/** @param toggles The diagram's switches with their state on this page. @returns Which are on and which are off. */
export function toggleStates(toggles: Pick<DiagramToggle, "id" | "on">[]): ToggleStates {
  return { on: toggles.filter((t) => t.on).map((t) => t.id), off: toggles.filter((t) => !t.on).map((t) => t.id) };
}

/**
 * The file name of an export.
 *
 * @param code The diagram's code ("DGM-001").
 * @param name The diagram's name, reduced to letters, digits and hyphens.
 * @param extension The file extension without a dot.
 * @returns For example `DGM-001-platform-overview.svg`.
 */
export function exportFileName(code: string, name: string, extension: string): string {
  const slug = name.toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 60).replace(/-+$/g, "");
  return `${code}${slug ? `-${slug}` : ""}.${extension}`;
}
