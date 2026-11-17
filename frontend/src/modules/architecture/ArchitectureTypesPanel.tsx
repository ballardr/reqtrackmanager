/**
 * Module: modules/architecture/ArchitectureTypesPanel
 *
 * The settings list of one vocabulary (element types, connection types or domains) for a project or for an organisation,
 * on the shared `DefinitionList`: inline rename, reorder, add and delete, with an Edit dialog (`TypeFormModal`) for
 * the other attributes (a domain is only a name, so it has none). In a project, a row that is an organisation default is read-only there: deleting it hides it
 * in this project (after a confirmation) and `RestoreOrgDefaultsButton` shows it again; to change a default, hide it
 * and add a type of the project's own. A type in use cannot be deleted (the server answers 409), so the message tells
 * the administrator to hide it instead.
 */
import { Pencil } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { DefinitionList } from "../../components/DefinitionList";
import { RestoreOrgDefaultsButton, type HiddenDefinition } from "../../components/RestoreOrgDefaultsButton";
import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { blockedError } from "../../utils/blockedError";
import { connectionTypeApi, domainApi, elementTypeApi, orgSymbolUrl, projectSymbolUrl, symbolApi } from "./api";
import { TypeFormModal } from "./TypeFormModal";
import {
  ELEMENT_SHAPE_LABEL, LINE_STYLE_LABEL,
  type ArchitectureDomain, type ArchitectureSymbol, type ConnectionType, type ConnectionTypeValues, type ElementType,
  type ElementTypeValues,
} from "./types";

type TypeRow = ElementType | ConnectionType | ArchitectureDomain;

/** The vocabulary a panel manages: the two type vocabularies and the domains they refer to. */
export type TypesKind = "element" | "connection" | "domain";

/** Where the vocabulary is managed: a project (its effective list) or an organisation (its defaults). */
export type TypesScope = { kind: "project"; projectId: string } | { kind: "org"; organizationId: string };

/** The inline colour dots of a row (light, dark); nothing when the type has no colour. */
function ColourDots({ row }: { row: TypeRow }) {
  if (!("color_light" in row) || (!row.color_light && !row.color_dark)) return null;
  return (
    <span className="row" style={{ gap: "var(--space-1)" }} aria-label={`Colours of ${row.name}`}>
      {[row.color_light, row.color_dark].map((hex, index) => hex && (
        <span key={index} aria-hidden="true" style={{ width: 14, height: 14, borderRadius: "50%", background: hex, border: "1px solid var(--color-border)" }} />
      ))}
    </span>
  );
}

/** "Software · Cylinder" / "Hardware · Dashed, one-way, default protocol SPI mode 0": what a type's row shows beside its name; a domain shows nothing. */
function summaryOf(row: TypeRow, rows: TypeRow[], domains: ArchitectureDomain[]): string {
  if (!("domain_ids" in row)) return "";
  const domainNames = row.domain_ids.map((id) => domains.find((d) => d.id === id)?.name).filter(Boolean);
  const detail = "shape" in row
    ? ELEMENT_SHAPE_LABEL[row.shape]
    : `${LINE_STYLE_LABEL[row.line_style]}, ${row.directional ? "one-way" : "two-way"}${row.default_protocol ? `, default protocol ${row.default_protocol}` : ""}`;
  const parents = "parent_ids" in row ? row.parent_ids.map((id) => rows.find((r) => r.id === id)?.name).filter(Boolean) : [];
  return `${domainNames.length > 0 ? domainNames.join(", ") : "Any domain"} · ${detail}${parents.length > 0 ? ` · Under ${parents.join(", ")}` : ""}`;
}

/**
 * @param scope The project or organisation whose vocabulary is managed.
 * @param kind Which vocabulary: element types, connection types or domains.
 */
export function ArchitectureTypesPanel({ scope, kind }: { scope: TypesScope; kind: TypesKind }) {
  const { showToast } = useToast();
  const noun = kind === "element" ? "element type" : kind === "connection" ? "connection type" : "domain";
  const [rows, setRows] = useState<TypeRow[] | null>(null);
  const [hidden, setHidden] = useState<HiddenDefinition[]>([]);
  const [symbols, setSymbols] = useState<ArchitectureSymbol[]>([]);
  const [connectionTypes, setConnectionTypes] = useState<ConnectionType[]>([]);
  const [domains, setDomains] = useState<ArchitectureDomain[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<TypeRow | "new" | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const reload = useCallback(() => setRefresh((n) => n + 1), []);

  const scopeId = scope.kind === "project" ? scope.projectId : scope.organizationId;
  const calls = (kind === "element" ? elementTypeApi : kind === "connection" ? connectionTypeApi : domainApi) as typeof elementTypeApi;
  const symbolUrl = (id: string) => (scope.kind === "project" ? projectSymbolUrl(scopeId, id) : orgSymbolUrl(scopeId, id));

  useEffect(() => {
    let live = true;
    const load = async () => {
      const list = scope.kind === "project" ? await calls.projectList(scopeId) : await calls.orgList(scopeId);
      const found = kind === "element"
        ? await (scope.kind === "project" ? symbolApi.projectList(scopeId) : symbolApi.orgList(scopeId))
        : [];
      // An element type's dialog chooses the connection types it suggests.
      const connections = kind === "element"
        ? await (scope.kind === "project" ? connectionTypeApi.projectList(scopeId) : connectionTypeApi.orgList(scopeId)).catch(() => [])
        : [];
      // A type's dialog and summary choose and name its domains.
      const foundDomains = kind === "domain"
        ? []
        : await (scope.kind === "project" ? domainApi.projectList(scopeId) : domainApi.orgList(scopeId)).catch(() => []);
      const hiddenRows = scope.kind === "project" ? await calls.projectHidden(scopeId).catch(() => []) : [];
      if (!live) return;
      setRows(list);
      setSymbols(found);
      setConnectionTypes(connections);
      setDomains(foundDomains);
      setHidden(hiddenRows);
      setLoadError(null);
    };
    load().catch((err) => { if (live) setLoadError(toErrorMessage(err, `Could not load the ${noun}s.`)); });
    return () => { live = false; };
  }, [scope.kind, scopeId, kind, noun, calls, refresh]);

  if (loadError) return <div style={{ color: "var(--color-danger)" }}>{loadError}</div>;
  if (rows === null) return <Spinner />;

  /** An organisation default seen from a project: read-only there, hidden rather than deleted. */
  const isOrgDefault = (row: TypeRow) => scope.kind === "project" && row.project_id === null;
  const find = (id: string) => rows.find((r) => r.id === id);

  async function save(values: ElementTypeValues | ConnectionTypeValues) {
    setFormError(null);
    try {
      if (editing === "new") {
        await (scope.kind === "project" ? calls.projectCreate(scopeId, values as never) : calls.orgCreate(scopeId, values as never));
        showToast(`${noun[0].toUpperCase()}${noun.slice(1)} created.`);
      } else if (editing) {
        await (scope.kind === "project"
          ? calls.projectUpdate(scopeId, editing.id, values as never)
          : calls.orgUpdate(scopeId, editing.id, values as never));
        showToast(`${noun[0].toUpperCase()}${noun.slice(1)} updated.`);
      }
      setEditing(null);
      reload();
    } catch (err) {
      setFormError(toErrorMessage(err, `Could not save the ${noun}.`));
    }
  }

  return (
    <div className="stack">
      <DefinitionList<TypeRow>
        layout="grid"
        items={rows}
        fields={[{
          key: "name", getValue: (item) => item.name, label: "Name", placeholder: `${noun[0].toUpperCase()}${noun.slice(1)} name`,
          ariaLabel: `${noun[0].toUpperCase()}${noun.slice(1)} name`, track: "minmax(10rem, 1fr)",
        }]}
        getReassignLabel={(item) => item.name}
        isReadOnly={isOrgDefault}
        minItems={0}
        onMove={async (id, direction) => {
          if (isOrgDefault(find(id) as TypeRow)) {
            showToast("Organisation defaults keep the organisation's order. Reorder the project's own types instead.", "error");
            return;
          }
          try {
            await (scope.kind === "project" ? calls.projectMove(scopeId, id, direction) : calls.orgMove(scopeId, id, direction));
            reload();
          } catch (err) {
            showToast(toErrorMessage(err, `Could not reorder the ${noun}s.`), "error");
          }
        }}
        onRename={async (id, values) => {
          await (scope.kind === "project"
            ? calls.projectUpdate(scopeId, id, { name: values.name } as never)
            : calls.orgUpdate(scopeId, id, { name: values.name } as never));
          reload();
        }}
        onAdd={async (values) => {
          const blank = kind === "domain"
            ? { name: values.name }
            : kind === "element"
              ? { name: values.name, domain_ids: [], shape: "rectangle", color_light: null, color_dark: null, symbol_id: null, suggested_connection_type_ids: [] }
              : { name: values.name, domain_ids: [], line_style: "solid", directional: true, default_protocol: "", color_light: null, color_dark: null, parent_ids: [] };
          await (scope.kind === "project" ? calls.projectCreate(scopeId, blank as never) : calls.orgCreate(scopeId, blank as never));
          showToast(`${noun[0].toUpperCase()}${noun.slice(1)} created.`);
          reload();
        }}
        onDelete={async (id) => {
          const row = find(id);
          try {
            await (scope.kind === "project" ? calls.projectDelete(scopeId, id) : calls.orgDelete(scopeId, id));
          } catch (err) {
            throw blockedError(
              err,
              kind === "domain"
                ? `This domain is still used by a type or a diagram switch. ${scope.kind === "project" ? "Hide it instead of deleting it." : "Change those first."}`
                : `This ${noun} is still used by a record. ${scope.kind === "project" ? "Hide it instead of deleting it." : "Change those records first."}`,
            );
          }
          showToast(row && isOrgDefault(row) ? `${noun[0].toUpperCase()}${noun.slice(1)} hidden in this project.` : `${noun[0].toUpperCase()}${noun.slice(1)} deleted.`);
          reload();
        }}
        deleteLabel={`Delete ${noun}`}
        getDeleteLabel={(item) => (isOrgDefault(item) ? `Hide ${noun} in this project` : `Delete ${noun}`)}
        confirmDelete={(item) => isOrgDefault(item)
          ? {
              title: `Hide "${item.name}" in this project?`,
              message: `It is an organisation default. It will no longer be offered in this project, and records that already use it keep it. Other projects are unaffected, and you can add it back with "Add organisation defaults".`,
              confirmLabel: "Hide",
            }
          : null}
        addLabel={`Add ${noun}`}
        renderExtra={(item) => (
          <span key="type-extra" className="row" style={{ gap: "var(--space-3)", alignItems: "center" }}>
            <span className="text-muted" style={{ fontSize: "0.8rem" }}>{summaryOf(item, rows, domains)}</span>
            <ColourDots row={item} />
            {scope.kind === "project" && item.project_id === null && <span className="text-muted" style={{ fontSize: "0.75rem" }}>Org default</span>}
            {kind !== "domain" && !isOrgDefault(item) && (
              <button
                className="btn" aria-label={`Edit ${item.name}`} title={`Edit ${item.name}`}
                onClick={() => { setFormError(null); setEditing(item); }}
              >
                <Pencil />
              </button>
            )}
          </span>
        )}
      />
      <div className="row" style={{ gap: "var(--space-3)" }}>
        {kind !== "domain" && (
          <button className="btn" onClick={() => { setFormError(null); setEditing("new"); }}>
            {`New ${noun} with details`}
          </button>
        )}
        {scope.kind === "project" && (
          <RestoreOrgDefaultsButton
            hidden={hidden}
            noun={`${noun}s`}
            onRestore={async (ids) => {
              await calls.projectRestore(scopeId, ids);
              showToast(ids.length === 1 ? "Organisation default added back." : `${ids.length} organisation defaults added back.`);
              reload();
            }}
          />
        )}
      </div>
      {editing && kind !== "domain" && (
        <TypeFormModal
          kind={kind}
          initial={editing === "new" ? undefined : (editing as ElementType | ConnectionType)}
          domains={domains}
          symbols={symbols}
          symbolUrl={symbolUrl}
          scope={scope}
          onSymbolsChanged={reload}
          connectionTypes={kind === "connection" ? (rows as ConnectionType[]) : connectionTypes}
          error={formError}
          onCancel={() => { setEditing(null); setFormError(null); }}
          onSave={save}
        />
      )}
    </div>
  );
}
