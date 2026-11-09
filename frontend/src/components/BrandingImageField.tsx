/**
 * Module: components/BrandingImageField
 *
 * The control for one organisation branding picture (the logo, the login page background): choose a file, see the
 * picture in use, remove the organisation's own file.
 *
 * Responsibilities: a file cannot be emptied, so the way back to the platform picture is an explicit Remove
 * button shown only while the organisation has its own file (no "Custom" pill). When it has none, the platform
 * picture is drawn muted under a "Platform default" caption so the person can see what is in use.
 * Upload and removal outcomes are the caller's: it supplies the handlers and the messages.
 */
import { Upload } from "lucide-react";

import { fileUrl } from "../api/client";
import { t } from "../i18n/strings";
import { InlineMessage } from "./InlineMessage";
import { UploadField } from "./FormFields";
import { PictureImage } from "./PictureImage";
import { Spinner } from "./Spinner";

const strings = t();

/**
 * @param id Id of the file input.
 * @param label Caption of the field.
 * @param fileId The organisation's own file, or null when it uses the platform picture.
 * @param platformFileId The platform picture shown when the organisation has none, or null for none.
 * @param busy An upload or removal is in progress (disables the controls and shows a spinner).
 * @param onSelect Called with the chosen file.
 * @param onRemove Called when Remove is pressed.
 * @param error An error message to show beside the control.
 * @param uploaded A success message to show beside the control.
 * @param height Height of the preview in pixels.
 */
export function BrandingImageField({
  id, label, fileId, platformFileId, busy, onSelect, onRemove, error, uploaded, height,
}: {
  id: string;
  label: string;
  fileId: string | null;
  platformFileId: string | null;
  busy: boolean;
  onSelect: (file: File) => void;
  onRemove: () => void;
  error?: string | null;
  uploaded?: string | null;
  height: number;
}) {
  return (
    <div className="stack" style={{ gap: "var(--space-2)" }}>
      <UploadField helpNotNeeded id={id} label={label} accept="image/*" disabled={busy} onSelect={onSelect}>
        <Upload size={14} /> {strings.common.chooseFile}
      </UploadField>
      {busy && <Spinner />}
      <InlineMessage>{error}</InlineMessage>
      <InlineMessage tone="success">{uploaded}</InlineMessage>
      {fileId ? (
        <div className="row" style={{ gap: "var(--space-3)", alignItems: "center" }}>
          <PictureImage src={fileUrl(fileId)} style={{ height, maxWidth: "100%" }} />
          <button type="button" className="btn" onClick={onRemove} disabled={busy}>{strings.common.remove}</button>
        </div>
      ) : platformFileId ? (
        <div className="row" style={{ gap: "var(--space-3)", alignItems: "center" }}>
          <PictureImage src={fileUrl(platformFileId)} style={{ height, maxWidth: "100%", opacity: 0.55 }} />
          <span className="text-muted">{strings.common.platformDefault}</span>
        </div>
      ) : null}
    </div>
  );
}
