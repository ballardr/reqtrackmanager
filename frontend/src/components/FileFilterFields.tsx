/**
 * Module: components/FileFilterFields
 *
 * The filter fields the project and organisation Files pages share, laid out inside a `FilterPanel`: source, file
 * type, uploader and the upload window (the file-name search is the panel's own search box).
 *
 * The state lives in the page (`useFileFilters`), so each page adds its own scope control beside these fields.
 */
import { PROJECT_FILE_SOURCES, type ProjectFileUploader } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { FILE_KINDS, type FileFilterState } from "../hooks/useFileFilters";
import { FilterSelect } from "./FilterSelect";
import { DateField } from "./FormFields";

/**
 * @param filters The page's filters (`useFileFilters`).
 * @param uploaders The people to offer under "Uploaded by".
 */
export function FileFilterFields({ filters, uploaders }: { filters: FileFilterState; uploaders: ProjectFileUploader[] }) {
  const strings = useStrings();
  return (
    <>
      <FilterSelect
        label={strings.files.filterSource}
        value={filters.source}
        onChange={filters.setSource}
        allLabel={strings.files.allSources}
        options={PROJECT_FILE_SOURCES.map((s) => ({ value: s, label: strings.files.sources[s] }))}
      />
      <FilterSelect
        label={strings.files.filterKind}
        value={filters.kind}
        onChange={filters.setKind}
        allLabel={strings.files.allKinds}
        options={FILE_KINDS.map((k) => ({ value: k, label: strings.files.kinds[k] }))}
      />
      <FilterSelect
        label={strings.files.filterUploader}
        value={filters.uploader}
        onChange={filters.setUploader}
        allLabel={strings.files.allUploaders}
        options={uploaders.map((u) => ({ value: u.id, label: u.display_name }))}
      />
      <DateField helpNotNeeded label={strings.files.uploadedFrom} value={filters.from} onChange={filters.setFrom} inputProps={{ max: filters.to || undefined }} />
      <DateField helpNotNeeded label={strings.files.uploadedTo} value={filters.to} onChange={filters.setTo} inputProps={{ min: filters.from || undefined }} />
    </>
  );
}
