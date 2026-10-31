import type { MergeConflict } from "../api/types";
import { useStrings } from "../context/TerminologyContext";

/**
 * Lets the caller resolve every name collision an org-merge preview
 * (`POST /orgs/{id}/import/preview`) reported, before committing via
 * `POST /orgs/{id}/import/merge`. A project conflict (and a module's own, such as a
 * Compliance standard) can only be skipped or imported as a renamed copy — never
 * overwritten in place, since a project carries real requirement/change-request
 * history a silent overwrite would destroy (see `services.org_export._import_projects`'s
 * docstring).
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
  const otherConflicts = conflicts.filter((c) => c.kind !== "project");

  return (
    <div className="stack">
      <strong>{strings.importMerge.conflictsTitle(conflicts.length)}</strong>
      {projectConflicts.length > 0 && (
        <div className="stack" style={{ gap: "var(--space-3)" }}>
          <span className="text-muted">{strings.importMerge.projectsSection}</span>
          {projectConflicts.map((c) => (
            <div key={c.id} className="card stack" style={{ gap: "var(--space-1)" }}>
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
      {otherConflicts.length > 0 && (
        <div className="stack" style={{ gap: "var(--space-3)" }}>
          <span className="text-muted">{strings.importMerge.otherSection}</span>
          {otherConflicts.map((c) => (
            <div key={c.id} className="card stack" style={{ gap: "var(--space-1)" }}>
              <strong>{c.name}</strong>
              <label>
                <input
                  type="radio" name={c.id} checked={resolutions[c.id] === "skip"}
                  onChange={() => onResolutionChange(c.id, "skip")}
                />{" "}
                {strings.importMerge.otherSkip}
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
    </div>
  );
}
