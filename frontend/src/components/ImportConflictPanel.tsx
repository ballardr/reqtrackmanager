import type { MergeConflict } from "../api/types";
import { useStrings } from "../context/TerminologyContext";

/**
 * Lets the caller resolve every project/report-template name collision an
 * org-merge preview (`POST /orgs/{id}/import/preview`) reported, before
 * committing via `POST /orgs/{id}/import/merge`. A project conflict can
 * only be skipped or imported as a renamed copy — never overwritten in
 * place, since a project carries real requirement/change-request history a
 * silent overwrite would destroy (see `services.org_export.
 * _import_projects`'s docstring). A report template conflict has no such
 * history, so it can be kept or overwritten directly.
 */
export function ImportConflictPanel({
  conflicts,
  resolutions,
  onResolutionChange,
}: {
  conflicts: MergeConflict[];
  resolutions: Record<string, string>;
  onResolutionChange: (id: string, value: string) => void;
}) {
  const strings = useStrings();
  const projectConflicts = conflicts.filter((c) => c.kind === "project");
  const templateConflicts = conflicts.filter((c) => c.kind === "report_template");

  return (
    <div className="stack">
      <strong>{strings.importMerge.conflictsTitle(conflicts.length)}</strong>
      {projectConflicts.length > 0 && (
        <div className="stack" style={{ gap: "0.5rem" }}>
          <span className="text-muted">{strings.importMerge.projectsSection}</span>
          {projectConflicts.map((c) => (
            <div key={c.id} className="card stack" style={{ gap: "0.25rem" }}>
              <strong>{c.name}</strong>
              <label>
                <input
                  type="radio" name={c.id} checked={resolutions[c.id] === "skip"}
                  onChange={() => onResolutionChange(c.id, "skip")}
                />{" "}
                {strings.importMerge.projectSkip}
              </label>
              <label>
                <input
                  type="radio" name={c.id} checked={resolutions[c.id] === "import_as_copy"}
                  onChange={() => onResolutionChange(c.id, "import_as_copy")}
                />{" "}
                {strings.importMerge.projectImportAsCopy}
              </label>
            </div>
          ))}
        </div>
      )}
      {templateConflicts.length > 0 && (
        <div className="stack" style={{ gap: "0.5rem" }}>
          <span className="text-muted">{strings.importMerge.reportTemplatesSection}</span>
          {templateConflicts.map((c) => (
            <div key={c.id} className="card stack" style={{ gap: "0.25rem" }}>
              <strong>{c.name}</strong>
              <label>
                <input
                  type="radio" name={c.id} checked={resolutions[c.id] === "keep_existing"}
                  onChange={() => onResolutionChange(c.id, "keep_existing")}
                />{" "}
                {strings.importMerge.templateKeepExisting}
              </label>
              <label>
                <input
                  type="radio" name={c.id} checked={resolutions[c.id] === "use_import"}
                  onChange={() => onResolutionChange(c.id, "use_import")}
                />{" "}
                {strings.importMerge.templateUseImport}
              </label>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
