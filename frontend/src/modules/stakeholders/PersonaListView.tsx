/**
 * Module: modules/stakeholders/PersonaListView
 *
 * The Persona list shared by the project page (`ProjectPersonasPage`) and the
 * organisation panel (`OrgPersonasPanel`): `RecordListView` configured with
 * Persona's own columns (Role, Weight) and its create form. The two callers
 * only differ in how they fetch, where a row navigates, and whether a Scope
 * column and the project's effective weight are shown, so those are props.
 */
import { PersonaFormModal } from "./PersonaFormModal";
import { RecordListView } from "./RecordListView";
import type { Persona, PersonaFieldValues } from "./types";
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
  return (
    <RecordListView<Persona, PersonaFieldValues>
      records={personas}
      ariaLabel={ariaLabel}
      sectionKey={sectionKey}
      noun="Persona"
      scopeLabel={scopeLabel}
      emptyText={emptyText}
      showScope={showScope}
      statusLabel={PERSONA_STATUS_LABEL}
      statusTone={PERSONA_STATUS_TONE}
      scopeLabels={PERSONA_SCOPE_LABEL}
      typeName={(p) => p.persona_type_name}
      searchText={(p) => `${p.name} ${p.role_title}`}
      columnsBeforeType={[{ key: "role", label: "Role", render: (p) => p.role_title || "—" }]}
      columnsAfterScope={[
        {
          key: "weight", label: "Weight",
          render: (p) => {
            const value = showEffectiveWeight ? p.effective_weight : p.weight;
            return value === null ? "—" : String(value);
          },
        },
      ]}
      includeArchived={includeArchived}
      onIncludeArchivedChange={onIncludeArchivedChange}
      onOpen={onOpen}
      onCreate={onCreate}
      renderCreateModal={(props) => <PersonaFormModal {...props} typeOptions={typeOptions} />}
    />
  );
}
