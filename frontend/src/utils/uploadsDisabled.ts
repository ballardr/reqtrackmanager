/**
 * Module: utils/uploadsDisabled
 *
 * Reads the structured 403 the server returns when a bundle or template carries files that cannot be stored
 * because file uploads are disabled (`services.files.resolve_bundle_files`), so an import or a create dialog can
 * offer to proceed without the files instead of showing a bare error.
 */
import { ApiError } from "../api/client";
import { ORGANIZATION_UPLOADS_DISABLED_CODE, STORAGE_QUOTA_EXCEEDED_CODE, UPLOADS_DISABLED_CODE } from "../api/types";

/** Which rule stops the files: the deployment-wide switch, the organisation's switch, or its storage limit. */
export type UploadsRefusalReason = "deployment" | "organization" | "quota";

/** What the dialog tells the person about the files that cannot be stored. */
export interface UploadsDisabledInfo {
  fileCount: number;
  fileBytes: number;
  reason: UploadsRefusalReason;
  /** The space left under the storage limit (only for the `quota` reason). */
  remainingBytes?: number;
}

const REASON_BY_CODE: Record<string, UploadsRefusalReason> = {
  [UPLOADS_DISABLED_CODE]: "deployment",
  [ORGANIZATION_UPLOADS_DISABLED_CODE]: "organization",
  [STORAGE_QUOTA_EXCEEDED_CODE]: "quota",
};

/**
 * @param err Anything thrown by an API call.
 * @returns The file count, total size and the rule that applied when `err` is the "files cannot be stored" refusal of
 *   an import or a create; `null` for any other error, including the plain refusal of a single upload (which has no
 *   file count).
 */
export function uploadsDisabledInfo(err: unknown): UploadsDisabledInfo | null {
  if (!(err instanceof ApiError) || err.status !== 403) return null;
  const detail = err.detail as { code?: unknown; file_count?: unknown; file_bytes?: unknown; remaining_bytes?: unknown } | undefined;
  const reason = typeof detail?.code === "string" ? REASON_BY_CODE[detail.code] : undefined;
  if (!detail || !reason || typeof detail.file_count !== "number") return null;
  return {
    fileCount: detail.file_count,
    fileBytes: typeof detail.file_bytes === "number" ? detail.file_bytes : 0,
    reason,
    remainingBytes: typeof detail.remaining_bytes === "number" ? detail.remaining_bytes : undefined,
  };
}
