/**
 * Module: api/fileConfidential
 *
 * The confidential mark on a file (`PATCH /files/{id}/confidential`): a confidential file is never printed by a report's
 * record-images block. The mark changes nothing else: who may open the file is unchanged. Allowed to the uploader and to
 * those who manage the file's project; anyone else gets a 403.
 */
import { api } from "./client";
import type { FileAsset } from "./types";

/** Sets or clears the mark and returns the file as it now is. */
export function setFileConfidential(fileId: string, confidential: boolean): Promise<FileAsset> {
  return api.patch<FileAsset>(`/api/v1/files/${fileId}/confidential`, { confidential });
}
