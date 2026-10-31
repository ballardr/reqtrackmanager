/**
 * Module: components/ReportImageField
 *
 * The control behind an image block's `file` field: shows the chosen picture and opens the layout tier's image
 * library, where a person picks a picture, uploads one or deletes one of their own.
 *
 * Responsibilities:
 * - Show the chosen picture (thumbnail and name), or that it is no longer in the library.
 * - Offer the organisation's own logo as the picture (`ORG_LOGO_FILE`), which the run reads from the organisation and
 *   which is not a library picture.
 * - List the library in a dialog (search by name, tier, size, which layouts use each), upload with feedback, and
 *   delete an owned picture behind a confirmation that names the layouts using it.
 * - Show what a selected picture says about itself (pixel size, and for a photograph when it was taken, the camera,
 *   its description and where), because photographs are rarely named usefully.
 * - Narrow the list to unused pictures (not in any layout's current or older version) and delete several at once: a
 *   "Delete several…" mode marks owned pictures, with one confirmation that says how many are still in use.
 * - Say where an upload goes: an organisation image is visible to every member's layouts, a project image only to
 *   this project's.
 *
 * Design decisions: the library comes in as a prop (`ReportImageLibrary`) so stories stay off the network; the file is
 * judged by the server (its bytes decide the type), so the client only rejects a file over the size cap before sending.
 * Pictures are shown through `fileUrl`, whose own gate admits only people who may read the picture.
 */
import { Trash2 } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useState } from "react";

import { fileUrl } from "../api/client";
import type { ReportImage, ReportImageLibrary, ReportImageList } from "../api/reportLayouts";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { useStrings } from "../context/TerminologyContext";
import { Badge } from "./Badge";
import { FormActions } from "./FormActions";
import { CheckboxField } from "./FormFields";
import { ConfirmDialog } from "./ConfirmDialog";
import { FieldShell } from "./FieldHelp";
import { FileDetailsFacts } from "./FileDetailsPanel";
import { useFileDetails, type FileDetailsState } from "../hooks/useFileDetails";
import { FileUploadTrigger } from "./FileUploadTrigger";
import { TextField } from "./FormFields";
import { Modal } from "./Modal";
import { Spinner } from "./Spinner";

const ACCEPT = "image/png,image/jpeg,image/gif,image/webp,image/svg+xml";

/** The `file` that stands for the organisation's logo (`services.report_org_values.ORG_LOGO_FILE`). */
export const ORG_LOGO_FILE = "org_logo";

/**
 * @param label The field's caption.
 * @param value The chosen picture's file id, or `""`.
 * @param library The calls that list, upload and delete pictures.
 * @param scope Where an upload goes, for the hint.
 * @param onChange Called with the chosen file id.
 * @param help The field's help text.
 * @param required Whether the block needs a picture.
 */
export function ReportImageField({
  label, value, library, scope, onChange, disabled, help, required,
}: {
  label: string;
  value: string;
  library: ReportImageLibrary;
  scope: "organization" | "project";
  onChange: (fileId: string) => void;
  disabled?: boolean;
  help?: string;
  required?: boolean;
}) {
  const text = useStrings().reportImages;
  const controlId = useId();
  const [listing, setListing] = useState<ReportImageList | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [open, setOpen] = useState(false);
  /** Bumped to read the library again after an upload or a delete. */
  const [reads, setReads] = useState(0);
  const reload = useCallback(() => setReads((n) => n + 1), []);

  useEffect(() => {
    let cancelled = false;
    library.list().then(
      (rows) => {
        if (cancelled) return;
        setListing(rows);
        setLoadError(false);
      },
      () => {
        if (!cancelled) setLoadError(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [library, reads]);

  const images = listing?.images ?? null;
  const isOrgLogo = value === ORG_LOGO_FILE;
  const chosen = images?.find((image) => image.id === value) ?? null;
  const gone = value !== "" && !isOrgLogo && images !== null && chosen === null;

  return (
    <FieldShell label={label} controlId={controlId} help={help} required={required}>
      <div className="row" style={{ gap: "var(--space-3)", alignItems: "center" }}>
        {value !== "" && !gone && !isOrgLogo && <img className="report-image-thumb" src={fileUrl(value)} alt="" />}
        <span className="text-muted" style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere" }}>
          {isOrgLogo ? text.organizationLogo : (chosen?.filename ?? (gone ? text.missing : value === "" ? text.none : "…"))}
        </span>
        {!isOrgLogo && (
          <button type="button" className="btn btn-sm" disabled={disabled} onClick={() => onChange(ORG_LOGO_FILE)}>
            {text.useOrganizationLogo}
          </button>
        )}
        <button
          id={controlId} type="button" className="btn btn-sm" disabled={disabled} onClick={() => setOpen(true)}
          aria-label={value === "" ? text.choose : text.change}
        >
          {value === "" ? text.choose : text.change}
        </button>
      </div>
      {loadError && <span role="alert" style={{ color: "var(--color-danger)" }}>{text.loadFailed}</span>}
      {open && (
        <ImageLibraryDialog
          images={images} maxBytes={listing?.max_image_bytes ?? null} library={library} scope={scope} value={value} onReload={reload}
          onPick={(id) => { onChange(id); setOpen(false); }} onClose={() => setOpen(false)}
        />
      )}
    </FieldShell>
  );
}

/** The dialog: search, upload, a grid of pictures, and the details of the one selected. */
function ImageLibraryDialog({
  images, maxBytes, library, scope, value, onReload, onPick, onClose,
}: {
  images: ReportImage[] | null;
  maxBytes: number | null;
  library: ReportImageLibrary;
  scope: "organization" | "project";
  value: string;
  onReload: () => void;
  onPick: (fileId: string) => void;
  onClose: () => void;
}) {
  const strings = useStrings();
  const text = strings.reportImages;
  const { showToast } = useToast();
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [removing, setRemoving] = useState<ReportImage | null>(null);
  const [unusedOnly, setUnusedOnly] = useState(false);
  const [marking, setMarking] = useState(false);
  const [marked, setMarked] = useState<ReadonlySet<string>>(new Set());
  const [confirmingMarked, setConfirmingMarked] = useState(false);
  const [selected, setSelected] = useState(value);
  const found = useFileDetails(selected === "" ? null : selected, library.details);

  const shown = useMemo(
    () => (images ?? []).filter(
      (image) => image.filename.toLowerCase().includes(search.trim().toLowerCase())
        && (!unusedOnly || (image.used_by.length === 0 && !image.in_older_versions)),
    ),
    [images, search, unusedOnly],
  );
  const ownedShown = shown.filter((image) => image.owned);
  const markedImages = (images ?? []).filter((image) => marked.has(image.id));
  const current = images?.find((image) => image.id === selected) ?? null;

  async function upload(file: File) {
    setError(null);
    if (maxBytes !== null && file.size > maxBytes) {
      setError(text.tooLarge(text.sizeKb(maxBytes)));
      return;
    }
    setBusy(true);
    try {
      const added = await library.upload(file);
      onReload();
      setSelected(added.id);
      showToast(text.uploaded(added.filename));
    } catch (err) {
      setError(toErrorMessage(err, text.loadFailed));
    } finally {
      setBusy(false);
    }
  }

  async function remove(image: ReportImage) {
    setRemoving(null);
    try {
      await library.remove(image.id);
      onReload();
      if (selected === image.id) setSelected("");
      showToast(text.removed(image.filename));
    } catch (err) {
      setError(toErrorMessage(err, text.loadFailed));
    }
  }

  function toggleMark(id: string, on: boolean) {
    setMarked((current) => {
      const next = new Set(current);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }

  function stopMarking() {
    setMarking(false);
    setMarked(new Set());
  }

  /** Deletes the marked pictures one after another; a failure does not stop the rest, and the toast says how many went. */
  async function removeMarked() {
    setConfirmingMarked(false);
    let done = 0;
    for (const image of markedImages) {
      try {
        await library.remove(image.id);
        done += 1;
      } catch {
        // counted below
      }
    }
    onReload();
    if (marked.has(selected)) setSelected("");
    stopMarking();
    const failed = markedImages.length - done;
    showToast(failed === 0 ? text.bulkDone(done) : text.bulkPartial(done, failed), failed === 0 ? undefined : "error");
  }

  return (
    <Modal title={text.dialogTitle} onClose={onClose} size="lg">
      <div className="stack">
        <div className="row" style={{ alignItems: "flex-end", gap: "var(--space-3)" }}>
          <div style={{ flex: 1 }}>
            <TextField label={text.search} value={search} onChange={setSearch} helpNotNeeded />
          </div>
          <FileUploadTrigger accept={ACCEPT} onSelect={(file) => void upload(file)} disabled={busy} className="btn">
            {busy ? text.uploading : text.upload}
          </FileUploadTrigger>
        </div>
        <span className="text-muted" style={{ fontSize: "0.8rem" }}>
          {text.uploadsTo(scope === "project" ? text.whereProject : text.whereOrganization)}
          {maxBytes !== null && ` ${text.limit(text.sizeKb(maxBytes))}`}
        </span>
        {images !== null && images.length > 0 && (
          <div className="row" style={{ alignItems: "center", gap: "var(--space-3)" }}>
            <CheckboxField label={text.unusedOnly} hint={text.unusedOnlyHint} helpNotNeeded checked={unusedOnly} onChange={setUnusedOnly} />
            <span style={{ marginInlineStart: "auto" }} className="row">
              {!marking && ownedShown.length > 0 && (
                <button type="button" className="btn btn-sm" onClick={() => setMarking(true)}>{text.deleteSeveral}</button>
              )}
              {marking && (
                <>
                  <strong aria-live="polite">{text.marked(markedImages.length)}</strong>
                  <button type="button" className="btn btn-sm" onClick={() => setMarked(new Set(ownedShown.map((i) => i.id)))}>{text.selectAllShown}</button>
                  <button type="button" className="btn btn-sm" disabled={marked.size === 0} onClick={() => setMarked(new Set())}>{text.clearMarks}</button>
                  <button type="button" className="btn btn-sm btn-danger" disabled={markedImages.length === 0} onClick={() => setConfirmingMarked(true)}>
                    {text.deleteMarked(markedImages.length)}
                  </button>
                  <button type="button" className="btn btn-sm" onClick={stopMarking}>{text.cancelDeleteSeveral}</button>
                </>
              )}
            </span>
          </div>
        )}
        {error && <div role="alert" style={{ color: "var(--color-danger)" }}>{error}</div>}
        {images === null && <Spinner />}
        {images !== null && images.length === 0 && <p className="text-muted" style={{ margin: 0 }}>{text.empty}</p>}
        {images !== null && images.length > 0 && shown.length === 0 && (
          <p className="text-muted" style={{ margin: 0 }}>{unusedOnly && search.trim() === "" ? text.noUnused : text.noMatches}</p>
        )}
        {images !== null && images.length > 0 && (
          <div className="report-image-browser">
            <ul className="report-image-grid" aria-label={text.dialogTitle}>
              {shown.map((image) => (
                <li key={image.id} className="report-image-card" data-selected={image.id === selected || undefined}>
                  <button
                    type="button" className="report-image-pick" aria-label={text.select(image.filename)} aria-pressed={image.id === selected}
                    onClick={() => setSelected(image.id)} onDoubleClick={() => onPick(image.id)}
                  >
                    <img src={fileUrl(image.id)} alt="" loading="lazy" />
                    <span className="report-image-name">{image.filename}</span>
                  </button>
                  <div className="row" style={{ gap: "var(--space-1)", justifyContent: "space-between", flexWrap: "wrap" }}>
                    <Badge tone={image.tier === "organisation" ? "info" : "accent"}>{text.tierLabels[image.tier]}</Badge>
                    <span className="text-muted" style={{ fontSize: "0.8rem" }}>{text.sizeKb(image.size_bytes)}</span>
                  </div>
                  <div className="row" style={{ justifyContent: "space-between", gap: "var(--space-1)" }}>
                    <span className="text-muted" style={{ fontSize: "0.8rem" }}>
                      {image.used_by.length === 0 && image.in_older_versions ? text.onlyOlderVersions : text.usedBy(image.used_by.length)}
                    </span>
                    {marking && image.owned && (
                      <input
                        type="checkbox" aria-label={text.selectToDelete(image.filename)} checked={marked.has(image.id)}
                        onChange={(e) => toggleMark(image.id, e.target.checked)}
                      />
                    )}
                    {!marking && image.owned && (
                      <button type="button" className="btn btn-sm btn-icon" aria-label={text.remove(image.filename)} onClick={() => setRemoving(image)}>
                        <Trash2 aria-hidden="true" />
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
            <ImageDetailsPanel image={current} found={found} />
          </div>
        )}
        <FormActions
          onCancel={onClose} onSave={() => onPick(selected)} saveLabel={text.use} saveDisabled={current === null}
        />
      </div>
      {confirmingMarked && (
        <ConfirmDialog
          title={text.bulkTitle(markedImages.length)}
          message={text.bulkMessage(markedImages.length, markedImages.filter((i) => i.used_by.length > 0).length)}
          confirmLabel={strings.common.delete} onConfirm={() => void removeMarked()} onCancel={() => setConfirmingMarked(false)}
        />
      )}
      {removing && (
        <ConfirmDialog
          title={text.removeTitle} message={text.removeMessage(removing.filename, removing.used_by)}
          confirmLabel={strings.common.delete} onConfirm={() => void remove(removing)} onCancel={() => setRemoving(null)}
        />
      )}
    </Modal>
  );
}

/** The selected picture, larger, with what the file records about itself (the shared facts list). */
function ImageDetailsPanel({ image, found }: { image: ReportImage | null; found: FileDetailsState }) {
  const text = useStrings().reportImages;
  if (image === null) return <aside className="report-image-details text-muted" aria-label={text.details}>{text.selectPrompt}</aside>;
  return (
    <aside className="report-image-details stack" aria-label={text.details}>
      <img src={fileUrl(image.id)} alt="" className="report-image-preview" />
      <strong style={{ overflowWrap: "anywhere" }}>{image.filename}</strong>
      <FileDetailsFacts found={found} />
      {image.used_by.length > 0 && <span className="text-muted">{text.usedByNames(image.used_by)}</span>}
    </aside>
  );
}
