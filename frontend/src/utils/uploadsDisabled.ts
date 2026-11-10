/**
 * Module: utils/uploadsDisabled
 *
 * Reads the structured 403 the server returns when a bundle or template carries files that cannot be stored
 * because file uploads are disabled (`services.files.resolve_bundle_files`), so an import or a create dialog can
 * offer to proceed without the files instead of showing a bare error.
 */
import { ApiError } from "../api/client";
import { UPLOADS_DISABLED_CODE } from "../api/types";

/** What the dialog tells the person about the files that cannot be stored. */
export interface UploadsDisabledInfo {
  fileCount: number;
  fileBytes: number;
}

/**
 * @param err Anything thrown by an API call.
 * @returns The file count and total size when `err` is the "files cannot be stored" refusal of an import or a
 *   create; `null` for any other error, including the plain refusal of a single upload (which has no file count).
 */
export function uploadsDisabledInfo(err: unknown): UploadsDisabledInfo | null {
  if (!(err instanceof ApiError) || err.status !== 403) return null;
  const detail = err.detail as { code?: unknown; file_count?: unknown; file_bytes?: unknown } | undefined;
  if (detail?.code !== UPLOADS_DISABLED_CODE || typeof detail.file_count !== "number") return null;
  return { fileCount: detail.file_count, fileBytes: typeof detail.file_bytes === "number" ? detail.file_bytes : 0 };
}
