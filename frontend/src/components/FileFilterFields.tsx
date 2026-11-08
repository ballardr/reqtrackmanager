/**
 * Module: components/FileFilterFields
 *
 * The filter fields the project and organisation Files pages share, laid out inside a `FilterPanel`: source, file
 * type, uploader and the upload window (the file-name search is the panel's own search box).
 *
 * The state lives in the page (`useFileFilters`), so each page adds its own scope control beside these fields.
 */
import { PROJECT_FILE_SOURCES, type ProjectFileKind, type ProjectFileSource, type ProjectFileUploader } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { FILE_KINDS, type FileFilterState } from "../hooks/useFileFilters";
import { FilterField } from "./FilterPanel";
import { DateField } from "./FormFields";

/**
 * @param filters The page's filters (`useFileFilters`).
 * @param uploaders The people to offer under "Uploaded by".
 */
export function FileFilterFields({ filters, uploaders }: { filters: FileFilterState; uploaders: ProjectFileUploader[] }) {
  const strings = useStrings();
  return (
    <>
      <FilterField label={strings.files.filterSource}>
        <select className="input" value={filters.source} onChange={(e) => filters.setSource(e.target.value as ProjectFileSource | "")}>
          <option value="">{strings.files.allSources}</option>
          {PROJECT_FILE_SOURCES.map((s) => (
            <option key={s} value={s}>{strings.files.sources[s]}</option>
          ))}
        </select>
      </FilterField>
      <FilterField label={strings.files.filterKind}>
        <select className="input" value={filters.kind} onChange={(e) => filters.setKind(e.target.value as ProjectFileKind | "")}>
          <option value="">{strings.files.allKinds}</option>
          {FILE_KINDS.map((k) => (
            <option key={k} value={k}>{strings.files.kinds[k]}</option>
          ))}
        </select>
      </FilterField>
      <FilterField label={strings.files.filterUploader}>
        <select className="input" value={filters.uploader} onChange={(e) => filters.setUploader(e.target.value)}>
          <option value="">{strings.files.allUploaders}</option>
          {uploaders.map((u) => (
            <option key={u.id} value={u.id}>{u.display_name}</option>
          ))}
        </select>
      </FilterField>
      <DateField helpNotNeeded label={strings.files.uploadedFrom} value={filters.from} onChange={filters.setFrom} inputProps={{ max: filters.to || undefined }} />
      <DateField helpNotNeeded label={strings.files.uploadedTo} value={filters.to} onChange={filters.setTo} inputProps={{ min: filters.from || undefined }} />
    </>
  );
}
