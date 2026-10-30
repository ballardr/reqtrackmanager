/**
 * Module: api/fileDetails
 *
 * What a picture file says about itself (`GET /files/{id}/details`): its size and, for a photograph, the EXIF a
 * person recognises it by. Open to whoever may download the file.
 */
import { api } from "./client";

/** `FileDetailsOut`; every part may be absent. */
export interface FileDetails {
  width_px: number | null;
  height_px: number | null;
  /** When it was taken on the camera's own clock, `YYYY-MM-DD HH:MM:SS` (EXIF has no time zone, so it is not converted). */
  taken: string | null;
  camera: string | null;
  description: string | null;
  latitude: number | null;
  longitude: number | null;
}

/** Reads a file's details. */
export function fetchFileDetails(fileId: string): Promise<FileDetails> {
  return api.get<FileDetails>(`/api/v1/files/${fileId}/details`);
}

const PICTURE_TYPES = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/svg+xml"];
const PICTURE_NAME = /\.(jpe?g|png|gif|webp|svg)$/i;

/**
 * Whether a file may have details worth showing: a picture (raster or SVG) by its declared type or, since an upload's declared
 * type is whatever the client sent, by its name.
 */
export function isPictureFile(file: { filename: string; content_type?: string }): boolean {
  return PICTURE_TYPES.includes(file.content_type ?? "") || PICTURE_NAME.test(file.filename);
}
