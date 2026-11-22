/**
 * Module: modules/architecture/SymbolUploadField
 *
 * The "Upload a symbol" file control with the server's refusal shown under it, used by the symbol picker's Upload view (the
 * library page has its own several-file dialog, `SymbolUploadDialog`). It owns no upload logic: the caller passes the state
 * from `useSymbolUpload`.
 */
import { UploadField } from "../../components/FormFields";
import { ARCHITECTURE_HELP } from "./help";
import type { SymbolUpload } from "./useSymbolUpload";

/**
 * @param id The file input's id (unique on the page).
 * @param state The upload action and its error from `useSymbolUpload`.
 * @param help The caption's help text (the settings panel and the picker explain different things).
 */
export function SymbolUploadField({
  id, state, help = ARCHITECTURE_HELP.symbolUpload,
}: { id: string; state: SymbolUpload; help?: string }) {
  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <UploadField
        id={id} label="Upload a symbol" accept=".svg,image/svg+xml,.eps,.pdf" help={help} disabled={state.busy}
        onSelect={(file) => void state.upload(file)}
      >
        Choose a file
      </UploadField>
      {state.error && <div role="alert" style={{ color: "var(--color-danger)" }}>{state.error}</div>}
    </div>
  );
}
