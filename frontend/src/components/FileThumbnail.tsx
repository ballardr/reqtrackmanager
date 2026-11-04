/**
 * Module: components/FileThumbnail
 *
 * A small preview beside a file's name in a file list: the picture itself for a picture, otherwise an icon for the
 * kind of file.
 *
 * Responsibilities:
 * - Draw a raster or SVG picture through `PictureImage` (so it sits on the person's chosen backdrop) from `fileUrl`,
 *   loaded lazily, with the file name as its alt text.
 * - Fall back to the file icon when a picture cannot be read (a missing object, a format the browser cannot draw).
 *
 * Design decisions: the picture is requested by `fileUrl`, so the server's own read check decides who sees it and the
 * thumbnail adds no access. An SVG is drawn by an `<img>`, never inlined into the page, so nothing in it can run.
 * Only a picture is requested at all; every other file shows an icon without a request.
 */
import { FileText, Image as ImageIcon } from "lucide-react";
import { useState } from "react";

import { isPictureFile } from "../api/fileDetails";
import { fileUrl } from "../api/client";
import { PictureImage } from "./PictureImage";

/**
 * @param file The file: its id, name (the alt text) and content type.
 */
export function FileThumbnail({ file }: { file: { id: string; filename: string; content_type: string } }) {
  const [failed, setFailed] = useState(false);
  if (isPictureFile(file) && !failed) {
    return <PictureImage className="file-thumb" src={fileUrl(file.id)} alt={file.filename} loading="lazy" onError={() => setFailed(true)} />;
  }
  const Icon = isPictureFile(file) ? ImageIcon : FileText;
  return (
    <span className="file-thumb file-thumb--icon" aria-hidden="true">
      <Icon size={20} />
    </span>
  );
}
