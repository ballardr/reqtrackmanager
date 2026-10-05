/**
 * Module: modules/stakeholders/PersonaListView
 *
 * The Persona list shared by the project page (`ProjectPersonasPage`) and the
 * organisation panel (`OrgPersonasPanel`): the `DirectoryTable` + `FilterPanel`
 * + "New Persona" `Modal` shape every module artefact list uses, with status
 * and type filters and the standard archived toggle. The two callers only
 * differ in how they fetch, where a row navigates, and whether a Scope column
 * and the project's effective weight are shown, so those are props rather
 * than a second copy of the list.
 *
 * Status and scope render through their label maps; status and type badges
 * are `FilterBadge`s because the same page filters on both (style guide
 * principle 10).
 */
import { useState } from "react";

import { DirectoryTable, type DirectoryColumn } from "../../components/DirectoryTable";
import { FilterBadge } from "../../components/FilterBadge";
import { FilterCheckbox, FilterField, FilterPanel } from "../../components/FilterPanel";
import { toErrorMessage } from "../../context/ToastContext";
import { PersonaFormModal } from "./PersonaFormModal";
import type { Persona, PersonaFieldValues, PersonaStatus } from "./types";
import { PERSONA_SCOPE_LABEL, PERSONA_STATUS_LABEL, PERSONA_STATUS_TONE } from "./types";

export function PersonaListView({
  personas,
  ariaLabel,
  sectionKey,
  scopeLabel,
  emptyText,
  showScope,
  showEffectiveWeight,
  typeOptions,
  includeArchived,
  onIncludeArchivedChange,
  onOpen,
  onCreate,
}: {
  personas: Persona[];
  ariaLabel: string;
  sectionKey: string;
  /** "project" / "organisation", for the create modal's title. */
  scopeLabel: string;
  emptyText: string;
  showScope: boolean;
  showEffectiveWeight: boolean;
  typeOptions: { value: string; label: string }[];
  includeArchived: boolean;
  onIncludeArchivedChange: (next: boolean) => void;
  onOpen: (persona: Persona) => void;
  /** Resolves on success; a rejection keeps the modal open and shows its message. */
  onCreate: (values: PersonaFieldValues) => Promise<void>;
}) {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<PersonaStatus | "">("");
  const [typeFilter, setTypeFilter] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  const typeNames = Array.from(new Set(personas.map((p) => p.persona_type_name).filter((n): n is string => !!n))).sort();
  const filtered = personas.filter((p) => {
    if (statusFilter && p.status !== statusFilter) return false;
    if (typeFilter && p.persona_type_name !== typeFilter) return false;
    if (search && !`${p.name} ${p.role_title}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const columns: DirectoryColumn<Persona>[] = [
    { key: "name", label: "Name", render: (p) => p.name },
    { key: "role", label: "Role", render: (p) => p.role_title || "—" },
    {
      key: "type", label: "Type",
      render: (p) =>
        p.persona_type_name ? (
          <FilterBadge active={typeFilter === p.persona_type_name} onClick={() => setTypeFilter(typeFilter === p.persona_type_name ? "" : (p.persona_type_name ?? ""))}>
            {p.persona_type_name}
          </FilterBadge>
        ) : "—",
    },
    ...(showScope
      ? [{ key: "scope", label: "Scope", render: (p: Persona) => PERSONA_SCOPE_LABEL[p.scope] } as DirectoryColumn<Persona>]
      : []),
    {
      key: "weight", label: "Weight",
      render: (p) => {
        const value = showEffectiveWeight ? p.effective_weight : p.weight;
        return value === null ? "—" : String(value);
      },
    },
    {
      key: "status", label: "Status",
      render: (p) => (
        <FilterBadge tone={PERSONA_STATUS_TONE[p.status]} active={statusFilter === p.status} onClick={() => setStatusFilter(statusFilter === p.status ? "" : p.status)}>
          {PERSONA_STATUS_LABEL[p.status]}
        </FilterBadge>
      ),
    },
  ];

  return (
    <div className="stack">
      <button className="btn btn-primary" style={{ alignSelf: "flex-start" }} onClick={() => setCreating(true)}>
        New Persona
      </button>
      <div className="side-grid">
        <DirectoryTable
          ariaLabel={ariaLabel}
          columns={columns}
          rows={filtered}
          rowKey={(p) => p.id}
          onRowClick={onOpen}
          emptyState={<p className="text-muted">{emptyText}</p>}
        />
        <FilterPanel
          sectionKey={sectionKey} total={filtered.length}
          search={search} onSearchChange={setSearch} searchPlaceholder="Search Personas…" searchAriaLabel={`Search ${ariaLabel}`}
        >
          <FilterField label="Status">
            <select className="input" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value as PersonaStatus | "")}>
              <option value="">All statuses</option>
              {Object.entries(PERSONA_STATUS_LABEL).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Type">
            <select className="input" value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
              <option value="">All types</option>
              {typeNames.map((name) => (
                <option key={name} value={name}>{name}</option>
              ))}
            </select>
          </FilterField>
          <FilterCheckbox label="Show archived" checked={includeArchived} onChange={onIncludeArchivedChange} />
        </FilterPanel>
      </div>

      {creating && (
        <PersonaFormModal
          scopeLabel={scopeLabel}
          typeOptions={typeOptions}
          error={createError}
          onCancel={() => { setCreating(false); setCreateError(null); }}
          onSave={async (values) => {
            setCreateError(null);
            try {
              await onCreate(values);
              setCreating(false);
            } catch (err) {
              setCreateError(toErrorMessage(err, "Could not create Persona."));
            }
          }}
        />
      )}
    </div>
  );
}
