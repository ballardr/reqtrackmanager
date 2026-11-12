/**
 * Module: modules/architecture/SymbolLibraryPanel
 *
 * The symbol library of a project or an organisation, on the shared `DefinitionList`: a preview and a rename beside each
 * symbol, reorder, upload and delete. A built-in symbol is drawn in code, so it cannot be renamed. In a project, a symbol that is an organisation default is read-only and deleting it hides it
 * here (restore with "Add organisation defaults"). An upload goes through the server's sanitiser, which refuses scripts,
 * external references and oversized files; the refusal is shown in the panel.
 */
import { useCallback, useEffect, useState } from "react";

import { DefinitionList } from "../../components/DefinitionList";
import { UploadField } from "../../components/FormFields";
import { RestoreOrgDefaultsButton, type HiddenDefinition } from "../../components/RestoreOrgDefaultsButton";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { blockedError } from "../../utils/blockedError";
import { orgSymbolUrl, projectSymbolUrl, symbolApi } from "./api";
import { ARCHITECTURE_HELP } from "./help";
import { SymbolImage } from "./SymbolImage";
import type { TypesScope } from "./ArchitectureTypesPanel";
import type { ArchitectureSymbol } from "./types";

/** @param scope The project or organisation whose library is managed. */
export function SymbolLibraryPanel({ scope }: { scope: TypesScope }) {
  const { showToast } = useToast();
  const [symbols, setSymbols] = useState<ArchitectureSymbol[] | null>(null);
  const [hidden, setHidden] = useState<HiddenDefinition[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);
  const scopeId = scope.kind === "project" ? scope.projectId : scope.organizationId;
  const urlFor = (id: string) => (scope.kind === "project" ? projectSymbolUrl(scopeId, id) : orgSymbolUrl(scopeId, id));

  useEffect(() => {
    let live = true;
    (async () => {
      const list = await (scope.kind === "project" ? symbolApi.projectList(scopeId) : symbolApi.orgList(scopeId));
      const hiddenRows = scope.kind === "project" ? await symbolApi.projectHidden(scopeId).catch(() => []) : [];
      if (!live) return;
      setSymbols(list);
      setHidden(hiddenRows);
      setLoadError(null);
    })().catch((err) => { if (live) setLoadError(toErrorMessage(err, "Could not load the symbol library.")); });
    return () => { live = false; };
  }, [scope.kind, scopeId, refresh]);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (symbols === null) return <Spinner />;

  /** Not renamed here: a built-in drawing, or (in a project) an organisation's symbol. */
  const isReadOnly = (symbol: ArchitectureSymbol) => symbol.is_builtin || (scope.kind === "project" && symbol.project_id === null);

  async function upload(file: File) {
    setUploadError(null);
    try {
      await (scope.kind === "project" ? symbolApi.projectUpload(scopeId, file) : symbolApi.orgUpload(scopeId, file));
      showToast("Symbol uploaded.");
      reload();
    } catch (err) {
      setUploadError(toErrorMessage(err, "Could not upload the symbol."));
    }
  }

  return (
    <div className="stack">
      <UploadField
        id="architecture-symbol-upload" label="Upload a symbol" accept=".svg,image/svg+xml,.eps,.pdf"
        help={ARCHITECTURE_HELP.symbolUpload} onSelect={(file) => void upload(file)}
      >
        Choose a file
      </UploadField>
      {uploadError && <div role="alert" style={{ color: "var(--color-danger)" }}>{uploadError}</div>}
      <DefinitionList<ArchitectureSymbol>
        layout="grid"
        items={symbols}
        fields={[{
          key: "name", getValue: (item) => item.name, label: "Name", placeholder: "Symbol name", ariaLabel: "Symbol name",
          track: "minmax(10rem, 1fr)",
        }]}
        getReassignLabel={(item) => item.name}
        isReadOnly={isReadOnly}
        minItems={0}
        onMove={async (id, direction) => {
          const row = symbols.find((s) => s.id === id);
          if (row && scope.kind === "project" && row.project_id === null) {
            showToast("Organisation symbols keep the organisation's order. Reorder the project's own symbols instead.", "error");
            return;
          }
          try {
            await (scope.kind === "project" ? symbolApi.projectMove(scopeId, id, direction) : symbolApi.orgMove(scopeId, id, direction));
            reload();
          } catch (err) {
            showToast(toErrorMessage(err, "Could not reorder the symbols."), "error");
          }
        }}
        onRename={async (id, values) => {
          await (scope.kind === "project" ? symbolApi.projectRename(scopeId, id, values.name) : symbolApi.orgRename(scopeId, id, values.name));
          reload();
        }}
        onAdd={async () => { /* A symbol is uploaded, never typed in. */ }}
        onDelete={async (id) => {
          const row = symbols.find((s) => s.id === id);
          try {
            await (scope.kind === "project" ? symbolApi.projectDelete(scopeId, id) : symbolApi.orgDelete(scopeId, id));
          } catch (err) {
            throw blockedError(err, "This symbol is still used by a type or an element. Choose another symbol for them first.");
          }
          showToast(row && scope.kind === "project" && row.project_id === null ? "Symbol hidden in this project." : "Symbol deleted.");
          reload();
        }}
        deleteLabel="Delete symbol"
        getDeleteLabel={(item) => (scope.kind === "project" && item.project_id === null ? "Hide symbol in this project" : "Delete symbol")}
        confirmDelete={(item) => scope.kind === "project" && item.project_id === null && !item.is_builtin
          ? {
              title: `Hide "${item.name}" in this project?`,
              message: "It is an organisation symbol. It will no longer be offered in this project, and types and elements that already use it keep it. You can add it back with \"Add organisation defaults\".",
              confirmLabel: "Hide",
            }
          : null}
        addLabel="Upload a symbol"
        renderExtra={(item) => (
          <span key="symbol-extra" className="row" style={{ gap: "var(--space-3)", alignItems: "center" }}>
            <SymbolImage src={urlFor(item.id)} alt={`Drawing of ${item.name}`} />
            {item.is_builtin && <span className="text-muted" style={{ fontSize: "0.75rem" }}>Built-in</span>}
          </span>
        )}
      />
      {scope.kind === "project" && (
        <div className="row">
          <RestoreOrgDefaultsButton
            hidden={hidden}
            noun="symbols"
            onRestore={async (ids) => {
              await symbolApi.projectRestore(scopeId, ids);
              showToast(ids.length === 1 ? "Organisation symbol added back." : `${ids.length} organisation symbols added back.`);
              reload();
            }}
          />
        </div>
      )}
    </div>
  );
}
