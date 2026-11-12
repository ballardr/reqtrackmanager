/**
 * Module: modules/architecture/AddElementsDialog
 *
 * Picks existing elements to place on a diagram: a table of the elements not yet on it (the project's own and those shared
 * with it), narrowed by search, element type and domain. "Add selected" places the ticked rows; "Add all matching" places
 * every row the filters leave, which is how a person adds, for example, every hardware element at once.
 */
import { useMemo, useState } from "react";

import { FormActions } from "../../components/FormActions";
import { TextField } from "../../components/FormFields";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { useRecordCode } from "../../hooks/useRecordCode";
import { labelOptions } from "../../utils/labelOptions";
import { DOMAIN_LABEL, type ArchitectureElement, type Domain, type ElementType } from "./types";

/**
 * @param candidates Elements that may be added (already filtered of those on the diagram and of archived ones).
 * @param elementTypes The project's element types, for the type filter and each element's domain.
 * @param onAdd Called with the chosen elements.
 */
export function AddElementsDialog({
  candidates, elementTypes, onCancel, onAdd,
}: {
  candidates: ArchitectureElement[];
  elementTypes: ElementType[];
  onCancel: () => void;
  onAdd: (elements: ArchitectureElement[]) => void;
}) {
  const formatCode = useRecordCode();
  const [search, setSearch] = useState("");
  const [typeId, setTypeId] = useState("");
  const [domain, setDomain] = useState<Domain | "">("");
  const [ticked, setTicked] = useState<Set<string>>(new Set());

  const domainOf = useMemo(() => new Map(elementTypes.map((t) => [t.id, t.domain])), [elementTypes]);
  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return candidates.filter((e) => {
      if (typeId && e.element_type_id !== typeId) return false;
      if (domain && domainOf.get(e.element_type_id) !== domain && domainOf.get(e.element_type_id) !== "any") return false;
      return !needle || `${e.unique_code} ${e.name} ${e.element_type_name}`.toLowerCase().includes(needle);
    });
  }, [candidates, search, typeId, domain, domainOf]);
  const chosen = candidates.filter((e) => ticked.has(e.id));

  const toggle = (id: string) => setTicked((current) => {
    const next = new Set(current);
    if (!next.delete(id)) next.add(id);
    return next;
  });

  return (
    <Modal title="Add existing elements" onClose={onCancel} size="lg">
      <div className="stack">
        <div className="row" style={{ alignItems: "flex-end" }}>
          <TextField helpNotNeeded label="Search" value={search} onChange={setSearch} />
          <LabeledSelect
            helpNotNeeded label="Element type" value={typeId} placeholder="All types" onChange={setTypeId}
            options={elementTypes.map((t) => ({ value: t.id, label: t.name }))}
          />
          <LabeledSelect
            helpNotNeeded label="Domain" value={domain} placeholder="All domains" onChange={(next) => setDomain(next as Domain | "")}
            options={labelOptions(DOMAIN_LABEL)}
          />
        </div>
        {shown.length === 0 ? (
          <p className="text-muted">{candidates.length === 0 ? "Every available element is already on this diagram." : "No elements match these filters."}</p>
        ) : (
          <table className="table">
            <thead>
              <tr><th scope="col">Add</th><th scope="col">Code</th><th scope="col">Name</th><th scope="col">Type</th></tr>
            </thead>
            <tbody>
              {shown.map((e) => (
                <tr key={e.id}>
                  <td>
                    <input type="checkbox" checked={ticked.has(e.id)} onChange={() => toggle(e.id)} aria-label={`Add ${e.name}`} />
                  </td>
                  <td>{formatCode.code(e.unique_code, e.from_project_code)}</td>
                  <td>{e.name}{e.shared ? " (shared)" : ""}</td>
                  <td>{e.element_type_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <FormActions
          onCancel={onCancel} onSave={() => onAdd(chosen)} saveLabel={`Add selected (${chosen.length})`} saveDisabled={chosen.length === 0}
        >
          <button type="button" className="btn" disabled={shown.length === 0} onClick={() => onAdd(shown)}>
            Add all matching ({shown.length})
          </button>
        </FormActions>
      </div>
    </Modal>
  );
}
