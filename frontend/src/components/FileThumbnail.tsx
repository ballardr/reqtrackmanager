/**
 * Module: components/FileThumbnail
 *
 * A small preview beside a file's name: the picture itself for a picture, otherwise an icon for the kind of file.
 * A raster or SVG picture is drawn lazily through `PictureImage` (on the person's chosen backdrop) from `fileUrl`
 * inside a button named "Preview <file name>" that opens `ImagePreviewDialog`; an unreadable picture falls back to
 * the icon, which is not a button, as is the icon of a file that is not a picture.
 *
 * `fileUrl` is requested, so the server's read check decides who sees it. An SVG is drawn by an `<img>`, never
 * inlined, so nothing in it can run. Only a picture is requested; other files show an icon with no request.
 */
import { FileText, Image as ImageIcon } from "lucide-react";
import { useState } from "react";

import { isPictureFile } from "../api/fileDetails";
import { fileUrl } from "../api/client";
import { useStrings } from "../context/TerminologyContext";
import { ImagePreviewDialog } from "./ImagePreviewDialog";
import { PictureImage } from "./PictureImage";
import { Tooltip } from "./Tooltip";

/**
 * @param file The file: its id, name (the preview's title) and content type.
 */
export function FileThumbnail({ file }: { file: { id: string; filename: string; content_type: string } }) {
  const text = useStrings().filePreview;
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  if (isPictureFile(file) && !failed) {
    const label = text.open(file.filename);
    return (
      <>
        <Tooltip label={label}>
          <button type="button" className="file-thumb-button" aria-label={label} aria-haspopup="dialog" onClick={() => setOpen(true)}>
            <PictureImage className="file-thumb" src={fileUrl(file.id)} loading="lazy" onError={() => setFailed(true)} />
          </button>
        </Tooltip>
        {open && <ImagePreviewDialog file={file} onClose={() => setOpen(false)} />}
      </>
    );
  }
  const Icon = isPictureFile(file) ? ImageIcon : FileText;
  return (
    <span className="file-thumb file-thumb--icon" aria-hidden="true">
      <Icon size={20} />
    </span>
  );
}
