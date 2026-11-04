/**
 * Module: components/ListActions
 *
 * The Export and Import controls of a record list (docs/ux-style-guide.md, "Pattern: list actions (export and
 * import)"), rendered by `ListPageLayout` beside the page's own actions so no list hand-builds them. They live
 * in one kebab menu ("List actions") next to the page's New button, not as separate buttons:
 *
 * - **Download shown items** opens a second list of formats: the CSV that re-imports, then the record-list report
 *   as PDF, Word, ODT or ODS, each narrowed by the page's own filters (never the full set; the word "shown" says
 *   so). The import template sits beside it. A note under the items says when the personal-data policy left
 *   columns out.
 * - **Download report** opens a dialog (`ReportDownloadDialog`) listing the reports that use the list's record
 *   type, in the Reports page's folders, and runs the chosen one in place.
 * - **Import from CSV** opens a file picker, then `CsvImportWizard`; it is offered only to a person who may
 *   create or update the type's records, and not at all for a type that gives a reason it cannot be imported.
 *
 * It serves a project's list and an organisation's own (the organisation panels) alike, through the owner it
 * is given. It reads the type's columns once (`GET .../records/{type}/columns`) and shows no menu when the type
 * has no table or the caller cannot see it. It knows no record type or module.
 *
 * A list that shows several record kinds at once (the People list) renders one `ListActions` per kind inside one
 * `ListActionsMenu`: each kind registers its items under a heading (its `kindLabel`, "Personas") and acts on its
 * own kind, while the person sees a single kebab. A `ListActions` rendered alone wraps itself in its own menu.
 */
import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react";

import { REPORT_FORMAT } from "../api/reportFormats";
import { omittedColumnsNote, RECORD_LIST_EXPORT_KINDS, recordOwner, recordTablesApi, type RecordColumns, type RecordTablesApi } from "../api/recordTables";
import { ProjectContext } from "../context/ProjectContextValue";
import { useRecordTableExport, fileStem } from "../hooks/useRecordTableExport";
import { t } from "../i18n/strings";
import { downloadBlob } from "../utils/download";
import { CODE_COLUMN_KEY, templateCsv } from "../utils/recordImport";
import { CsvImportWizard } from "./CsvImportWizard";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { ReportDownloadDialog } from "./ReportDownloadDialog";
import { FileUploadTrigger } from "./FileUploadTrigger";

const strings = t();

/** What a list page tells `ListPageLayout` so it can offer Export and Import. */
export interface RecordListActions {
  /** The project whose list this is; give this or `organizationId`, never both. */
  projectId?: string;
  /** The organisation whose own records this list shows (an organisation panel), instead of a project's. */
  organizationId?: string;
  /** The registered record type string. */
  recordType: string;
  /** The page's filters as a query string without `?` (the same names its list request sends, minus paging and sort). */
  filters?: string;
  /** Names the kind when a list shows several (`personas`): the buttons then read "Export personas". */
  kindLabel?: string;
  /** Called after an import wrote records, so the page reloads its list. */
  onImported?: () => void;
  /** Injectable calls (stories pass fakes). */
  tables?: RecordTablesApi;
}

/** What one kind of record contributes to the shared menu. */
interface KindEntry {
  items: ActionMenuItem[];
  /** One muted line under the items (columns the personal-data policy left out). */
  note?: string;
  /** True while a download is in flight; the menu's trigger is disabled meanwhile. */
  busy: boolean;
}

type Register = (id: string, entry: KindEntry | null) => void;

const RegisterContext = createContext<Register | null>(null);

/**
 * The one kebab menu of a list's export and import actions. Each `ListActions` rendered inside registers its items
 * here; the menu is shown once at least one kind has any.
 *
 * @param children The `ListActions` of the list, one per record kind.
 */
export function ListActionsMenu({ children }: { children: ReactNode }) {
  const [entries, setEntries] = useState<Record<string, KindEntry>>({});
  const register = useCallback<Register>((id, entry) => {
    setEntries((prev) => {
      if (entry === null) {
        const rest = { ...prev };
        delete rest[id];
        return rest;
      }
      return prev[id] === entry ? prev : { ...prev, [id]: entry };
    });
  }, []);

  const all = Object.values(entries);
  const items = all.flatMap((entry) => entry.items);
  const notes = all.map((entry) => entry.note).filter((note): note is string => !!note);
  return (
    <RegisterContext.Provider value={register}>
      {children}
      {items.length > 0 && (
        <ActionMenu
          triggerLabel={strings.recordTables.menuLabel}
          items={items}
          disabled={all.some((entry) => entry.busy)}
          footer={notes.length > 0 ? notes.map((note) => <span key={note} style={{ display: "block" }}>{note}</span>) : undefined}
        />
      )}
    </RegisterContext.Provider>
  );
}

/**
 * Adds one record kind's export and import items to the list's menu (its own menu when rendered alone).
 *
 * @param projectId The project whose list this is (or `organizationId` for an organisation's own records).
 * @param organizationId The organisation whose own records the list shows.
 * @param recordType The registered record type.
 * @param filters The page's current filters as a query string.
 * @param kindLabel Names the kind when the list shows several (a heading over its items).
 * @param onImported Called after an import wrote records.
 * @param tables Injectable calls.
 */
export function ListActions(props: RecordListActions) {
  const register = useContext(RegisterContext);
  return register ? <KindActions {...props} register={register} /> : (
    <ListActionsMenu>
      <ListActions {...props} />
    </ListActionsMenu>
  );
}

function KindActions({
  projectId, organizationId, recordType, filters = "", kindLabel, onImported, tables = recordTablesApi, register,
}: RecordListActions & { register: Register }) {
  const id = useId();
  const [columns, setColumns] = useState<RecordColumns | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [exporting, setExporting] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const projectOrganizationId = useContext(ProjectContext).organizationId ?? undefined;
  const pickerRef = useRef<HTMLInputElement>(null);
  const label = columns?.label ?? "";
  const owner = useMemo(() => recordOwner({ projectId, organizationId }), [projectId, organizationId]);
  const { exportList } = useRecordTableExport(owner, recordType, label, filters, tables);

  useEffect(() => {
    let active = true;
    tables.columns(owner, recordType).then((value) => active && setColumns(value)).catch(() => active && setColumns(null));
    return () => {
      active = false;
    };
  }, [owner, recordType, tables]);

  const downloadTemplate = useCallback(() => {
    if (!columns) return;
    const writable = columns.columns.filter((c) => c.key === CODE_COLUMN_KEY || (c.importable && c.included));
    downloadBlob(new Blob([templateCsv(writable)], { type: "text/csv" }), `${fileStem(columns.label)}-import-template.csv`);
  }, [columns]);

  const items = useMemo<ActionMenuItem[]>(() => {
    if (!columns) return [];
    const group = kindLabel ? kindLabel.charAt(0).toUpperCase() + kindLabel.slice(1) : undefined;
    const downloadShown: ActionMenuItem = {
      key: `${recordType}:download-shown`,
      group,
      label: strings.recordTables.downloadShownItems,
      onSelect: () => undefined,
      children: RECORD_LIST_EXPORT_KINDS.map((kind): ActionMenuItem => ({
        key: `${recordType}:export:${kind}`,
        label: REPORT_FORMAT[kind].label,
        title: REPORT_FORMAT[kind].title,
        hint: kind === "csv" ? strings.recordTables.csvReimportHint : undefined,
        onSelect: () => {
          setExporting(true);
          void exportList(kind).finally(() => setExporting(false));
        },
      })),
    };
    const downloadReport: ActionMenuItem = {
      key: `${recordType}:report`, group, label: strings.recordTables.downloadReport, onSelect: () => setReportOpen(true),
    };
    if (!(columns.importable && columns.can_import)) return [downloadReport, downloadShown];
    return [
      downloadReport,
      downloadShown,
      { key: `${recordType}:template`, group, label: strings.recordTables.downloadTemplate, onSelect: downloadTemplate },
      { key: `${recordType}:import`, group, label: strings.recordTables.importFromCsv, onSelect: () => pickerRef.current?.click() },
    ];
  }, [columns, kindLabel, recordType, exportList, downloadTemplate]);

  const note = columns ? omittedColumnsNote(columns) || undefined : undefined;
  // Registered on mount (empty) so kinds keep their render order however late each one's columns arrive.
  useEffect(() => {
    register(id, { items, note, busy: exporting });
  }, [register, id, items, note, exporting]);
  useEffect(() => () => register(id, null), [register, id]);

  if (!columns) return null;
  return (
    <>
      {columns.importable && columns.can_import && (
        <FileUploadTrigger ref={pickerRef} showTrigger={false} accept=".csv,text/csv" onSelect={setFile}>{null}</FileUploadTrigger>
      )}
      {reportOpen && (
        <ReportDownloadDialog
          projectId={projectId} organizationId={organizationId ?? projectOrganizationId} ownedByOrganization={!!organizationId}
          recordType={recordType} recordLabel={label} onClose={() => setReportOpen(false)}
        />
      )}
      {file && (
        <CsvImportWizard
          owner={owner} recordType={recordType} columns={columns} file={file} tables={tables}
          onClose={() => setFile(null)} onApplied={() => onImported?.()}
        />
      )}
    </>
  );
}
