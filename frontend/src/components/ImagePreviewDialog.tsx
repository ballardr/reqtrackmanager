/**
 * Module: components/ImagePreviewDialog
 *
 * A larger view of a picture file, opened from its thumbnail (`FileThumbnail`) in a file list.
 *
 * Responsibilities: draw the picture fitted to the window in the shared `Modal`, name the file in the title and
 * offer a Download link. Escape and the header close control close it; focus returns to the thumbnail (`Modal`).
 *
 * Design decisions: the picture is a `PictureImage`, so a transparent or dark logo stays visible on the person's
 * chosen backdrop. A raster keeps its natural size up to the dialog (never upscaled); an SVG has no natural size,
 * so it fills the dialog's width at a fixed height. An SVG is drawn by an `<img>`, never inlined, so nothing in it
 * can run. The URL is `fileUrl`, so the server's read check decides who sees it.
 */
import { useState } from "react";

import { fileUrl } from "../api/client";
import { useStrings } from "../context/TerminologyContext";
import { Modal } from "./Modal";
import { PictureImage } from "./PictureImage";

/** Whether a file is a vector picture, by its declared type or its name. */
function isVector(file: { filename: string; content_type: string }): boolean {
  return file.content_type === "image/svg+xml" || /\.svg$/i.test(file.filename);
}

/**
 * @param file The picture: its id, name and declared type.
 * @param onClose Closes the dialog.
 */
export function ImagePreviewDialog({
  file, onClose,
}: { file: { id: string; filename: string; content_type: string }; onClose: () => void }) {
  const text = useStrings().filePreview;
  const [failed, setFailed] = useState(false);
  const src = fileUrl(file.id);
  return (
    <Modal title={file.filename} size="lg" onClose={onClose}>
      {failed ? (
        <p role="alert" className="text-muted">{text.unreadable}</p>
      ) : (
        <PictureImage
          className={isVector(file) ? "image-preview image-preview--vector" : "image-preview"}
          src={src} alt={file.filename} onError={() => setFailed(true)}
        />
      )}
      <a href={src} download={file.filename} className="btn btn-sm" style={{ alignSelf: "flex-start" }}>{text.download}</a>
    </Modal>
  );
}
