/**
 * Module: api/reportFileNames
 *
 * The live example beside a "File name" field (`POST /report-file-names/example`): what a file name template would
 * call a downloaded report, filled with sample values, or what is wrong with it. The server is the judge, so the
 * example can never disagree with a real download. It reads and stores nothing.
 */
import { api } from "./client";

/** Where a template is set; decides which placeholders are allowed. */
export type FileNameKind = "layout" | "pack" | "entry" | "organization";

/** The file extensions the example can show. */
export type FileNameExtension = "pdf" | "docx" | "odt" | "html" | "csv" | "xlsx" | "ods" | "zip";

export interface FileNameExampleRequest {
  template: string;
  kind: FileNameKind;
  /** Names of the run-time variables the place declares (a layout's or a pack's). */
  variables: string[];
  extension: FileNameExtension;
}

export interface FileNameExample {
  /** The file name the template gives, or `null` when it is empty or has problems. */
  example: string | null;
  problems: string[];
  /** What the template may use here, ready to insert: `{{report_title}}`, `{{var.team}}` ... */
  placeholders: string[];
}

/** Asks the server what `request.template` would name a file. */
export function fetchFileNameExample(request: FileNameExampleRequest): Promise<FileNameExample> {
  return api.post<FileNameExample>("/api/v1/report-file-names/example", request);
}
