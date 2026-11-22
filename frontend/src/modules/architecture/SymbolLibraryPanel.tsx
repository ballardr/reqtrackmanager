/**
 * Module: modules/architecture/SymbolLibraryPanel
 *
 * The symbol library of the organisation (a section of Org Resources) or of a project (a section of its settings): the one
 * list page both homes render, so a project gets the same filters and folders as the organisation.
 *
 * - A `ListPageLayout` page: one primary button (Upload symbols) and one actions menu (the folder actions and, in a project,
 *   Add organisation defaults), a filter panel (search by name, Source, Used, File type and Folders) and the symbols as a
 *   sortable table or as tiles. The filters, the sort and the folder are in the page address; the server filters, sorts and
 *   pages (`useSymbolLibrary`).
 * - A project's page offers the organisation's symbols too, read-only: under their folder path in an Organisation branch of
 *   the folder tree, and hidden with Delete (restored with Add organisation defaults). Its own symbols have the project's own
 *   folders. A symbol inherited from a parent project is not filed.
 * - A built-in symbol is drawn in code: it cannot be renamed or filed. An upload goes through the server's sanitiser, which
 *   refuses scripts, external references and oversized files; each file's refusal is shown in the upload dialog.
 *
 * Controls render only for a person who may change the library (`useCanUploadSymbols`); the server enforces the same roles.
 */
import { useCallback, useMemo, useState } from "react";

import type { ActionMenuItem } from "../../components/ActionMenu";
import { ConfirmDialog } from "../../components/ConfirmDialog";
import { FilterPanel } from "../../components/FilterPanel";
import { FilterSelect } from "../../components/FilterSelect";
import { ListPageLayout } from "../../components/ListPageLayout";
import { LoadMoreButton } from "../../components/LoadMoreButton";
import { RestoreOrgDefaultsDialog, type HiddenDefinition } from "../../components/RestoreOrgDefaultsButton";
import { Spinner } from "../../components/Spinner";
import { cycleSort } from "../../components/sortState";
import { useViewMode, ViewToggle } from "../../components/ViewToggle";
import { useOrgLabelCapitalized } from "../../context/BrandingContext";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { useLoadOnChange } from "../../hooks/useLoadOnChange";
import { useUrlChoice, useUrlSort, useUrlText } from "../../hooks/useUrlFilter";
import { blockedError } from "../../utils/blockedError";
import { orgSymbolUrl, projectSymbolUrl, symbolApi } from "./api";
import type { TypesScope } from "./ArchitectureTypesPanel";
import { ARCHITECTURE_HELP } from "./help";
import { SymbolLibraryTable } from "./SymbolLibraryTable";
import { SymbolLibraryTiles } from "./SymbolLibraryTiles";
import type { SymbolRowActionContext } from "./symbolLibraryActions";
import { SymbolRenameModal } from "./SymbolRenameModal";
import { SymbolUploadDialog } from "./SymbolUploadDialog";
import { SymbolUsageModal } from "./SymbolUsageModal";
import {
  SYMBOL_FILE_TYPE_LABEL, SYMBOL_FILE_TYPES, SYMBOL_SORT_KEYS, SYMBOL_SOURCE_LABEL, SYMBOL_USED_LABEL, type SymbolLibraryFolder,
  type SymbolLibraryRow,
} from "./types";
import { useFolderListControls } from "./useFolderListControls";
import { useCanUploadSymbols } from "./useSymbolUpload";
import { useSymbolLibrary } from "./useSymbolLibrary";

const SOURCES = ["builtin", "uploaded"] as const;
const USED = ["used", "unused"] as const;
const NO_FOLDERS: SymbolLibraryFolder[] = [];

/** @param scope The project or organisation whose library is managed. */
export function SymbolLibraryPanel({ scope }: { scope: TypesScope }) {
  const { showToast } = useToast();
  const organizationLabel = useOrgLabelCapitalized();
  const inProject = scope.kind === "project";
  const scopeId = scope.kind === "project" ? scope.projectId : scope.organizationId;
  const canManage = useCanUploadSymbols(scope);
  const urlFor = useCallback(
    (id: string) => (scope.kind === "project" ? projectSymbolUrl(scopeId, id) : orgSymbolUrl(scopeId, id)),
    [scope.kind, scopeId],
  );

  const [search, setSearch] = useUrlText("q");
  const [source, setSource] = useUrlChoice("source", SOURCES);
  const [used, setUsed] = useUrlChoice("used", USED);
  const [fileType, setFileType] = useUrlChoice("filetype", SYMBOL_FILE_TYPES);
  const [sort, setSort] = useUrlSort<string>(SYMBOL_SORT_KEYS);
  const [viewMode, setViewMode] = useViewMode("architecture-symbols", "list");
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);
  const [branchFolders, setBranchFolders] = useState<SymbolLibraryFolder[]>(NO_FOLDERS);
  const [hidden, setHidden] = useState<HiddenDefinition[]>([]);

  const branch = useMemo(
    () => (inProject ? { label: organizationLabel, folders: branchFolders.map((f) => ({ path: f.path, count: f.symbol_count })) } : undefined),
    [inProject, organizationLabel, branchFolders],
  );
  const folders = useFolderListControls(
    scope.kind === "project" ? { projectId: scope.projectId } : { organizationId: scope.organizationId }, "symbol", "symbols", reload, true, branch,
  );
  const library = useSymbolLibrary(scope, {
    search: search.trim() || undefined, source: source || undefined, used: used || undefined, file_type: fileType || undefined,
    folder: folders.folderPath || undefined, folder_scope: folders.folderPath ? (folders.inBranch ? "organization" : "own") : undefined,
    subfolders: folders.folderPath ? !folders.exactFolder : undefined, sort: sort?.key, order: sort?.direction,
  }, refresh, (page) => setBranchFolders(page.organization_folders));

  // The organisation symbols this project has hidden (what "Add organisation defaults" can show again); only an administrator reads them.
  useLoadOnChange(async () => {
    setHidden(scope.kind === "project" && canManage ? await symbolApi.projectHidden(scope.projectId).catch(() => [] as HiddenDefinition[]) : []);
  }, [scope.kind, scopeId, canManage, refresh]);

  const [uploading, setUploading] = useState(false);
  const [renaming, setRenaming] = useState<SymbolLibraryRow | null>(null);
  const [deleting, setDeleting] = useState<SymbolLibraryRow | null>(null);
  const [usageOf, setUsageOf] = useState<SymbolLibraryRow | null>(null);
  const [restoring, setRestoring] = useState(false);

  const filtered = Boolean(search.trim() || source || used || fileType || folders.folderPath);
  const reorderable = canManage && sort === null && !filtered;

  async function move(row: SymbolLibraryRow, direction: "up" | "down") {
    try {
      await (scope.kind === "project" ? symbolApi.projectMove(scopeId, row.id, direction) : symbolApi.orgMove(scopeId, row.id, direction));
      reload();
    } catch (err) {
      showToast(toErrorMessage(err, "Could not reorder the symbols."), "error");
    }
  }

  async function remove(row: SymbolLibraryRow) {
    setDeleting(null);
    try {
      await (scope.kind === "project" ? symbolApi.projectDelete(scopeId, row.id) : symbolApi.orgDelete(scopeId, row.id));
      showToast(inProject && row.tier === "organization" ? "Symbol hidden in this project." : "Symbol deleted.");
      reload();
    } catch (err) {
      showToast(toErrorMessage(blockedError(err, "This symbol is still used by a type or an element. Choose another symbol for them first."), "Could not delete the symbol."), "error");
    }
  }

  const actions: SymbolRowActionContext | null = canManage
    ? { inProject, reorderable, onRename: setRenaming, onMove: (row, direction) => void move(row, direction), onDelete: setDeleting }
    : null;

  const menuItems = useMemo<ActionMenuItem[]>(() => {
    if (!canManage) return [];
    const items = [...folders.menuItems];
    if (hidden.length > 0) items.push({ key: "restore", label: `Add organisation defaults (${hidden.length})`, onSelect: () => setRestoring(true) });
    return items;
  }, [canManage, folders.menuItems, hidden.length]);

  if (library.error) return <div role="alert" style={{ color: "var(--color-danger)" }}>{library.error}</div>;
  const rows = library.rows;

  const emptyState = (
    <p className="text-muted">
      {library.libraryTotal === 0 ? "The symbol library is empty." : "No symbols match these filters."}
    </p>
  );

  return (
    <>
      <ListPageLayout
        title="Symbols"
        ready={rows !== null} loadedRows={rows?.length}
        actions={canManage ? <button className="btn btn-primary" onClick={() => setUploading(true)}>Upload symbols</button> : undefined}
        menuItems={menuItems}
        filter={(
          <FilterPanel
            sectionKey={`architecture.symbols.${scope.kind}`} total={library.total}
            search={search} onSearchChange={setSearch} searchPlaceholder="Search symbols…" searchAriaLabel="Search symbols"
          >
            <FilterSelect
              label="Source" help={ARCHITECTURE_HELP.symbolSource} value={source} onChange={setSource} allLabel="All sources"
              options={SOURCES.map((value) => ({ value, label: SYMBOL_SOURCE_LABEL[value] }))}
            />
            <FilterSelect
              label="Used" help={ARCHITECTURE_HELP.symbolUsed} value={used} onChange={setUsed} allLabel="Used or not"
              options={USED.map((value) => ({ value, label: SYMBOL_USED_LABEL[value] }))}
            />
            {(library.converterAvailable || fileType) && (
              <FilterSelect
                label="File type" help={ARCHITECTURE_HELP.symbolFileType} value={fileType} onChange={setFileType} allLabel="All file types"
                options={SYMBOL_FILE_TYPES.filter((t) => library.converterAvailable || t === "svg" || t === fileType).map((value) => ({ value, label: SYMBOL_FILE_TYPE_LABEL[value] }))}
              />
            )}
            {folders.panel}
          </FilterPanel>
        )}
      >
        {rows === null ? <Spinner /> : (
          <>
            <div className="row" style={{ justifyContent: "space-between", alignItems: "center" }}>
              <div>{canManage && folders.bar}</div>
              <ViewToggle mode={viewMode === "tiles" ? "tiles" : "list"} onChange={setViewMode} />
            </div>
            {viewMode === "tiles" ? (
              rows.length === 0 ? emptyState : (
                <>
                  <SymbolLibraryTiles
                    rows={rows} urlFor={urlFor} organizationLabel={organizationLabel} actions={actions}
                    selected={folders.selected} onSelectedChange={folders.setSelected} onShowUsage={setUsageOf}
                  />
                  <LoadMoreButton loaded={rows.length} total={library.total} onClick={library.loadMore} />
                </>
              )
            ) : (
              <SymbolLibraryTable
                rows={rows} urlFor={urlFor} organizationLabel={organizationLabel} actions={actions}
                sort={sort} onSort={(key) => setSort(cycleSort(sort, key))} onShowUsage={setUsageOf} emptyState={emptyState}
                total={library.total} onLoadMore={library.loadMore}
                selection={canManage ? {
                  selected: folders.selected, onChange: folders.setSelected, label: (r) => `Select ${r.name}`,
                  allLabel: "Select all symbols", selectable: (r) => r.can_file,
                } : undefined}
              />
            )}
          </>
        )}
      </ListPageLayout>
      {folders.dialog}
      {uploading && (
        <SymbolUploadDialog
          scope={scope} folders={folders.folders} defaultFolderId={folders.chosenFolderId} converterAvailable={library.converterAvailable}
          onClose={(count) => { setUploading(false); if (count > 0) reload(); }}
        />
      )}
      {renaming && (
        <SymbolRenameModal
          name={renaming.name} onClose={() => setRenaming(null)}
          onSave={async (name) => {
            await (scope.kind === "project" ? symbolApi.projectRename(scopeId, renaming.id, name) : symbolApi.orgRename(scopeId, renaming.id, name));
            showToast("Symbol renamed.");
            reload();
          }}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title={inProject && deleting.tier === "organization" ? `Hide "${deleting.name}" in this project?` : `Delete symbol "${deleting.name}"?`}
          message={inProject && deleting.tier === "organization"
            ? "It is an organisation symbol. It will no longer be offered in this project, and types and elements that already use it keep it. You can add it back with \"Add organisation defaults\"."
            : "The symbol and its file are removed. A symbol that an element type or an element uses cannot be deleted."}
          confirmLabel={inProject && deleting.tier === "organization" ? "Hide" : "Delete"}
          onCancel={() => setDeleting(null)} onConfirm={() => void remove(deleting)}
        />
      )}
      {usageOf && <SymbolUsageModal scope={scope} symbol={usageOf} onClose={() => setUsageOf(null)} />}
      {restoring && (
        <RestoreOrgDefaultsDialog
          hidden={hidden} noun="symbols" onClose={() => setRestoring(false)}
          onRestore={async (ids) => {
            await symbolApi.projectRestore(scopeId, ids);
            showToast(ids.length === 1 ? "Organisation symbol added back." : `${ids.length} organisation symbols added back.`);
            reload();
          }}
        />
      )}
    </>
  );
}
