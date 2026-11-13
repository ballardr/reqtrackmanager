/**
 * Module: modules/architecture/ElementFields
 *
 * The fields of an element that both the create and the edit form take (name, type, parent, folder, owner, symbol,
 * description, display note), as one group so a field added later reaches both. The element type, parent and symbol
 * choices belong to the element's owner (a project or the organisation), so the caller supplies them.
 */
import type { OrgUser } from "../../api/types";
import { savedPrincipalDisplay } from "../../api/types";
import { TextAreaField, TextField } from "../../components/FormFields";
import { FormGridFull } from "../../components/FormGrid";
import { LabeledSelect } from "../../components/LabeledSelect";
import { PrincipalFormField } from "../../components/PrincipalFormField";
import { useRecordCode } from "../../hooks/useRecordCode";
import { FolderField } from "./FolderField";
import { ARCHITECTURE_HELP } from "./help";
import { SymbolPicker } from "./SymbolPicker";
import type { ArchitectureElement, ArchitectureSymbol, ElementFieldValues, ElementType } from "./types";

/**
 * @param values The form's current values.
 * @param onChange Called with the changed field.
 * @param elementTypes The types that may be chosen.
 * @param parents The elements that may be this element's parent (same owner; never itself or a descendant).
 * @param symbols The symbols that may be chosen.
 * @param symbolUrl The API path of a symbol's content.
 * @param orgUsers Organisation members offered as owner.
 * @param organizationId The owning organisation, for user search and groups.
 * @param projectId The owning project (omit for an organisation element), for project groups.
 * @param saved The element being edited, so its owner shows by name until changed.
 */
export function ElementFields({
  values, onChange, elementTypes, parents, symbols, symbolUrl, orgUsers, organizationId, projectId, saved,
}: {
  values: ElementFieldValues;
  onChange: <K extends keyof ElementFieldValues>(key: K, value: ElementFieldValues[K]) => void;
  elementTypes: ElementType[];
  parents: ArchitectureElement[];
  symbols: ArchitectureSymbol[];
  symbolUrl: (symbolId: string) => string;
  orgUsers: OrgUser[];
  organizationId: string;
  projectId?: string;
  saved?: ArchitectureElement;
}) {
  const formatCode = useRecordCode();
  return (
    <>
      <FormGridFull>
        <TextField helpNotNeeded required label="Name" value={values.name} onChange={(value) => onChange("name", value)} />
      </FormGridFull>
      <LabeledSelect
        help={ARCHITECTURE_HELP.elementType} required label="Element type" value={values.element_type_id} placeholder="Choose a type"
        onChange={(next) => onChange("element_type_id", next)} options={elementTypes.map((t) => ({ value: t.id, label: t.name }))}
      />
      <LabeledSelect
        help={ARCHITECTURE_HELP.elementParent} label="Parent element" value={values.parent_id ?? ""} placeholder="None (top level)"
        onChange={(next) => onChange("parent_id", next || null)}
        options={parents.map((e) => ({ value: e.id, label: `${formatCode.code(e.unique_code)} ${e.name}` }))}
      />
      <FolderField
        kind="element" owner={projectId ? { projectId } : { organizationId }} value={values.folder_id}
        onChange={(next) => onChange("folder_id", next)}
      />
      <PrincipalFormField
        help={ARCHITECTURE_HELP.elementOwner} label="Owner" orgUsers={orgUsers} organizationId={organizationId} projectId={projectId}
        value={values.owner} display={savedPrincipalDisplay(values.owner, saved?.owner)}
        onChange={(next) => onChange("owner", next)} ariaLabel="Owner" placeholder="Search users and groups…" clearLabel="Clear"
      />
      <SymbolPicker
        help={ARCHITECTURE_HELP.elementSymbol} label="Symbol" symbols={symbols} value={values.symbol_id}
        onChange={(next) => onChange("symbol_id", next)} urlFor={symbolUrl} emptyLabel="Use the type's symbol"
      />
      <FormGridFull>
        <TextAreaField
          help={ARCHITECTURE_HELP.elementDescription} label="Description" value={values.description}
          onChange={(value) => onChange("description", value)}
        />
      </FormGridFull>
      <FormGridFull>
        <TextAreaField
          help={ARCHITECTURE_HELP.elementDisplayNote} label="Display note" value={values.display_note}
          onChange={(value) => onChange("display_note", value)} hint="Up to 500 characters" inputProps={{ maxLength: 500 }}
        />
      </FormGridFull>
    </>
  );
}
