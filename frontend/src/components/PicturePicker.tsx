/**
 * Module: components/PicturePicker
 *
 * The panel in which a picture is chosen from a record's attachments, uploaded as a new attachment, and given its
 * alternative text and caption, and the toolbar button that opens it.
 *
 * Responsibilities:
 * - `PicturePickerPopover`: step one lists the record's pictures as thumbnails (and offers an upload that attaches the
 *   file to the record and chooses it); step two shows the chosen picture with its alternative text and caption and
 *   hands the choice back on Insert (or Apply, for a picture being changed, which skips step one).
 * - `PictureToolbarButton`: the Picture button of every Markdown editor toolbar; it renders only where the editor sits
 *   inside a record page that supplies a picture source (`MarkdownImageSourceProvider`).
 *
 * Design decisions:
 * - A picture is always an attachment of the record, so there is nothing to type: no address field. An upload made here
 *   is an ordinary attachment (it appears in the Attachments card) and is chosen at once, which is the whole
 *   "upload while inserting" flow, as the symbol picker does for a symbol.
 * - Alternative text and caption are optional; an empty alternative text is allowed (the picture is then described
 *   only by its caption, and the filename is not used as a stand-in).
 * - One panel serves the Write view, the Visual view and a change to a picture already in the Visual view.
 *
 * Dependencies: `Popover`, `ToolbarButton`, `TextField`, `FileUploadTrigger`, `MarkdownImageSource`, `api/fileDetails`.
 */
import { ImagePlus } from "lucide-react";
import { useRef, useState, type FormEvent, type RefObject } from "react";

import { isPictureFile } from "../api/fileDetails";
import { fileUrl } from "../api/client";
import type { FileAsset } from "../api/types";
import { toErrorMessage } from "../context/ToastContext";
import { useStrings } from "../context/TerminologyContext";
import { MAX_CAPTION_CHARS } from "../utils/markdownPicture";
import { TextField } from "./FormFields";
import { FileUploadTrigger } from "./FileUploadTrigger";
import { useMarkdownImageSource, type MarkdownImageSource } from "./markdownImageSourceContext";
import { Popover } from "./Popover";
import { ToolbarButton } from "./ToolbarButton";

/** What a person chose: the attachment and the words that go with the picture. */
export interface PictureChoice {
  fileId: string;
  alt: string;
  caption: string;
}

/** The file types the upload accepts: the pictures an `<img>` draws and a report prints. */
const ACCEPT = "image/png,image/jpeg,image/gif,image/webp,image/svg+xml,.png,.jpg,.jpeg,.gif,.webp,.svg";

/**
 * @param anchorRef The button (or picture) the panel opens from.
 * @param source The record's attachments and its upload.
 * @param initial The picture being changed; absent for a new picture (the panel starts at the list of pictures).
 * @param onApply Called with the choice when the person confirms.
 * @param onClose Called when the panel is dismissed.
 */
export function PicturePickerPopover({ anchorRef, source, initial, onApply, onClose }: {
  anchorRef: RefObject<HTMLElement | null>;
  source: MarkdownImageSource;
  initial?: PictureChoice;
  onApply: (choice: PictureChoice) => void;
  onClose: () => void;
}) {
  const strings = useStrings();
  const text = strings.richText;
  const [fileId, setFileId] = useState<string | null>(initial?.fileId ?? null);
  const [alt, setAlt] = useState(initial?.alt ?? "");
  const [caption, setCaption] = useState(initial?.caption ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const changing = initial !== undefined;
  const pictures = source.files.filter(isPictureFile);

  async function upload(file: File) {
    if (!source.upload) return;
    setBusy(true);
    setError(null);
    try {
      const attached = await source.upload(file);
      setFileId(attached.id);
    } catch (err) {
      setError(toErrorMessage(err, text.pictureUploadFailed));
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    event.stopPropagation(); // a form inside an editor field's form must not submit the record
    if (fileId) onApply({ fileId, alt: alt.trim(), caption: caption.trim() });
  }

  const title = changing ? text.pictureChangeTitle : text.pictureInsertTitle;
  return (
    <Popover anchorRef={anchorRef} onClose={onClose} title={title} fit>
      {fileId === null ? (
        <div className="stack picture-picker" style={{ gap: "var(--space-2)", minWidth: "min(26rem, 80vw)" }}>
          <span className="text-muted" style={{ fontSize: "0.8rem", fontWeight: 600 }}>{text.pictureChoose}</span>
          {pictures.length === 0 ? (
            <p className="text-muted" role="status" style={{ margin: 0 }}>{text.pictureNone}</p>
          ) : (
            <div className="picture-picker__grid" role="group" aria-label={text.pictureChoose}>
              {pictures.map((file: FileAsset) => (
                <button
                  key={file.id} type="button" className="picture-picker__choice" aria-label={text.pictureFile(file.filename)}
                  onClick={() => setFileId(file.id)}
                >
                  <img className="picture-picker__thumb" src={fileUrl(file.id)} alt="" loading="lazy" />
                  <span>{file.filename}</span>
                </button>
              ))}
            </div>
          )}
          {source.upload ? (
            <FileUploadTrigger accept={ACCEPT} disabled={busy} onSelect={(file) => void upload(file)} title={text.pictureUpload} aria-label={text.pictureUpload}>
              {busy ? text.pictureUploading : text.pictureUpload}
            </FileUploadTrigger>
          ) : (
            <p className="text-muted" role="status" style={{ margin: 0 }}>{text.pictureNoUpload}</p>
          )}
          {error && <div role="alert" style={{ color: "var(--color-danger)" }}>{error}</div>}
          <div className="row" style={{ justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-sm" onClick={onClose}>{strings.common.cancel}</button>
          </div>
        </div>
      ) : (
        <form className="stack picture-picker" onSubmit={submit} style={{ gap: "var(--space-2)", minWidth: "min(24rem, 80vw)" }}>
          <img className="picture-picker__preview" src={fileUrl(fileId)} alt={text.picturePreview} />
          <TextField
            label={text.pictureAlt} value={alt} onChange={setAlt} help={strings.help.pictureAlt}
            inputProps={{ autoFocus: true, autoComplete: "off" }}
          />
          <TextField
            label={text.pictureCaption} value={caption} onChange={setCaption} help={strings.help.pictureCaption}
            inputProps={{ maxLength: MAX_CAPTION_CHARS, autoComplete: "off" }}
          />
          <div className="row" style={{ justifyContent: "flex-end" }}>
            {!changing && <button type="button" className="btn btn-sm" onClick={() => setFileId(null)}>{text.pictureBack}</button>}
            <button type="button" className="btn btn-sm" onClick={onClose}>{strings.common.cancel}</button>
            <button type="submit" className="btn btn-sm btn-primary">{changing ? text.pictureApply : text.pictureInsert}</button>
          </div>
        </form>
      )}
    </Popover>
  );
}

/**
 * The Picture button of a Markdown editor toolbar. Renders nothing where the field is not inside a record page that
 * supplies a picture source (a create form, a comment box).
 *
 * @param onInsert Called with the choice when the person confirms; the editor puts the picture in the field.
 * @param disabled Whether editing is unavailable.
 */
export function PictureToolbarButton({ onInsert, disabled }: { onInsert: (choice: PictureChoice) => void; disabled?: boolean }) {
  const source = useMarkdownImageSource();
  const text = useStrings().richText;
  const anchor = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  if (!source) return null;
  return (
    <>
      <ToolbarButton icon={ImagePlus} label={text.picture} disabled={disabled} buttonRef={anchor} opens={open} onClick={() => setOpen((current) => !current)} />
      {open && (
        <PicturePickerPopover
          anchorRef={anchor} source={source} onClose={() => setOpen(false)}
          onApply={(choice) => { setOpen(false); onInsert(choice); }}
        />
      )}
    </>
  );
}
