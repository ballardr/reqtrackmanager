/**
 * Module: components/FileThumbnail
 *
 * A small preview beside a file's name: the picture itself for a picture, otherwise an icon for the kind of file.
 * A raster or SVG picture is drawn lazily through `PictureImage` (on the person's chosen backdrop) from `fileUrl`
 * with the file name as alt text, and falls back to the icon when it cannot be read.
 *
 * `fileUrl` is requested, so the server's read check decides who sees it. An SVG is drawn by an `<img>`, never
 * inlined, so nothing in it can run. Only a picture is requested; other files show an icon with no request.
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
