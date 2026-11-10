/**
 * Module: components/UploadsDisabledPrompt
 *
 * The choice an import or a create from a template offers when its source carries files and file uploads are
 * disabled: cancel, or continue without the files. It replaces the form inside the dialog (the same dialog, one
 * step further) so the person never meets a bare error.
 *
 * Responsibilities: state how many files (and how much data) cannot be stored, and offer exactly two actions.
 * The caller repeats the request with `skip_files` when the person continues; the server ignores that flag
 * while files can be stored, so the default is always to import them.
 */
import { useStrings } from "../context/TerminologyContext";
import { formatFileSize } from "../utils/formatFileSize";
import type { UploadsDisabledInfo } from "../utils/uploadsDisabled";

/**
 * @param info The file count and total size reported by the server.
 * @param onCancel Abandons the import; nothing has been written.
 * @param onContinue Repeats the request without the files.
 * @param busy True while the repeated request runs.
 */
export function UploadsDisabledPrompt({
  info, onCancel, onContinue, busy = false,
}: {
  info: UploadsDisabledInfo;
  onCancel: () => void;
  onContinue: () => void;
  busy?: boolean;
}) {
  const strings = useStrings();
  return (
    <div className="stack" role="alert">
      <p style={{ margin: 0 }}>{strings.fileUploads.cannotStore(info.fileCount, formatFileSize(info.fileBytes))}</p>
      <div className="row" style={{ justifyContent: "flex-end" }}>
        <button className="btn" onClick={onCancel} disabled={busy}>{strings.fileUploads.cancelImport}</button>
        <button className="btn btn-primary" onClick={onContinue} disabled={busy}>{strings.fileUploads.importWithoutFiles}</button>
      </div>
    </div>
  );
}
