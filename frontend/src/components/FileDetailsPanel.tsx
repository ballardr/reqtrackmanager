/**
 * Module: components/FileDetailsPanel
 *
 * The one way a picture's own details (pixel size, and for a photograph when it was taken, the camera, its description
 * and where) are shown, wherever a file is listed.
 *
 * Responsibilities:
 * - `FileDetailsFacts`: the facts as a list, or a plain line when the file records none.
 * - `FileDetailsToggle`: an info button for a file row that opens the facts in a `Popover`, shown only for pictures.
 *
 * Design decisions: the details come from `GET /files/{id}/details`, which is open to exactly the people who may download
 * the file, so showing them adds no access. EXIF is the file's own text and is rendered as text only. "Taken" is the
 * camera's clock as written (EXIF has no time zone). The position is shown as numbers, with no link to a map service.
 */
import { Info } from "lucide-react";
import { useRef, useState } from "react";

import { isPictureFile, type FileDetails } from "../api/fileDetails";
import { useFileDetails, type FileDetailsState } from "../hooks/useFileDetails";
import { useStrings } from "../context/TerminologyContext";
import { Popover } from "./Popover";
import { Spinner } from "./Spinner";

/** The facts of `found`, a spinner while it is being read, or a line saying why there are none. */
export function FileDetailsFacts({ found }: { found: FileDetailsState }) {
  const text = useStrings().fileDetails;
  if (found === undefined) return <Spinner />;
  if (found === "failed") return <span role="alert" style={{ color: "var(--color-danger)" }}>{text.failed}</span>;
  const rows: [string, string][] = [];
  if (found.width_px && found.height_px) rows.push([text.pixels, `${found.width_px} × ${found.height_px} px`]);
  if (found.taken) rows.push([text.taken, found.taken]);
  if (found.camera) rows.push([text.camera, found.camera]);
  if (found.description) rows.push([text.description, found.description]);
  if (found.latitude !== null && found.longitude !== null) rows.push([text.location, `${found.latitude.toFixed(5)}, ${found.longitude.toFixed(5)}`]);
  const recorded = Boolean(found.taken || found.camera || found.description || found.latitude !== null);
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      {rows.length > 0 && (
        <dl className="report-image-facts">
          {rows.map(([label, value]) => (
            <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
          ))}
        </dl>
      )}
      {!recorded && <span className="text-muted">{text.noMetadata}</span>}
    </div>
  );
}

/**
 * An info button beside a file's name that opens its details. Renders nothing for a file that is not a picture.
 *
 * @param file The file (its id, name and declared type).
 * @param load Reads the details (the live call by default).
 */
export function FileDetailsToggle({
  file, load,
}: { file: { id: string; filename: string; content_type?: string }; load?: (id: string) => Promise<FileDetails> }) {
  const text = useStrings().fileDetails;
  const [open, setOpen] = useState(false);
  const anchor = useRef<HTMLButtonElement>(null);
  const found = useFileDetails(open ? file.id : null, load);
  if (!isPictureFile(file)) return null;
  return (
    <>
      <button
        ref={anchor} type="button" className="btn btn-sm btn-icon" aria-label={text.show(file.filename)} aria-expanded={open}
        onClick={() => setOpen((on) => !on)}
      >
        <Info aria-hidden="true" />
      </button>
      {open && (
        <Popover anchorRef={anchor} onClose={() => setOpen(false)} title={text.title(file.filename)}>
          <div className="stack">
            <strong style={{ overflowWrap: "anywhere" }}>{file.filename}</strong>
            <FileDetailsFacts found={found} />
          </div>
        </Popover>
      )}
    </>
  );
}
