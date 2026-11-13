/**
 * Module: modules/architecture/AddElementsDialog
 *
 * Picks existing elements to place on a diagram: a table of the elements not yet on it (the project's own and those shared
 * with it), narrowed by search, element type and domain. "Add selected" places the ticked rows; "Add all matching" places
 * every row the filters leave, which is how a person adds, for example, every hardware element at once. The component
 * filter is the shared collapsible tree of the project's components (`placementTree`); an element matches when it sits
 * in any ticked component or category. Only the project's own elements carry components (an element shared from another
 * owner has none here), so ticking a component narrows the list to the project's own.
 */
import { useEffect, useMemo, useState } from "react";

import { recordPlacementsApi, type Placement, type PlacementTree, type RecordPlacementsApi } from "../../api/placements";
import { FieldCaption } from "../../components/FieldHelp";
import { FormActions } from "../../components/FormActions";
import { TextField } from "../../components/FormFields";
import { LabeledSelect } from "../../components/LabeledSelect";
import { Modal } from "../../components/Modal";
import { placementNodes, placesOfNodeIds } from "../../components/placementTree";
import { TreeSelect } from "../../components/TreeSelect";
import { useStrings } from "../../context/TerminologyContext";
import { useRecordCode } from "../../hooks/useRecordCode";
import { labelOptions } from "../../utils/labelOptions";
import { DOMAIN_LABEL, type ArchitectureElement, type Domain, type ElementType } from "./types";

/** The most records one placements read answers for (the server's page limit). */
const PLACEMENT_PAGE = 500;

/**
 * Loads the project's component tree and the places of the candidate elements.
 *
 * @param projectId The project the diagram belongs to.
 * @param candidates The elements offered.
 * @param api The placement calls.
 * @returns The tree (null until read, or when the read fails: the filter is then not offered) and `{element id: places}`.
 */
function useCandidatePlacements(projectId: string, candidates: ArchitectureElement[], api: RecordPlacementsApi) {
  const [tree, setTree] = useState<PlacementTree | null>(null);
  const [places, setPlaces] = useState<Record<string, Placement[]>>({});
  // Keyed by the ids themselves, so a parent that rebuilds the list on every render does not re-read.
  const key = candidates.map((e) => e.id).join(",");
  useEffect(() => {
    let active = true;
    const ids = key ? key.split(",") : [];
    const chunks: string[][] = [];
    for (let i = 0; i < ids.length; i += PLACEMENT_PAGE) chunks.push(ids.slice(i, i + PLACEMENT_PAGE));
    Promise.all([api.tree(projectId), Promise.all(chunks.map((chunk) => api.page(projectId, "architecture_element", chunk)))])
      .then(([loaded, pages]) => {
        if (!active) return;
        setTree(loaded);
        setPlaces(Object.assign({}, ...pages));
      })
      .catch(() => active && setTree(null));
    return () => {
      active = false;
    };
  }, [api, projectId, key]);
  return { tree, places };
}

/**
 * @param projectId The project the diagram belongs to (its component tree is offered as a filter).
 * @param candidates Elements that may be added (already filtered of those on the diagram and of archived ones).
 * @param elementTypes The project's element types, for the type filter and each element's domain.
 * @param onAdd Called with the chosen elements.
 * @param placementsApi Injectable calls (stories pass a fake).
 */
export function AddElementsDialog({
  projectId, candidates, elementTypes, onCancel, onAdd, placementsApi = recordPlacementsApi,
}: {
  projectId: string;
  placementsApi?: RecordPlacementsApi;
  candidates: ArchitectureElement[];
  elementTypes: ElementType[];
  onCancel: () => void;
  onAdd: (elements: ArchitectureElement[]) => void;
}) {
  const formatCode = useRecordCode();
  const strings = useStrings();
  const { tree, places } = useCandidatePlacements(projectId, candidates, placementsApi);
  const [componentNodeIds, setComponentNodeIds] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [typeId, setTypeId] = useState("");
  const [domain, setDomain] = useState<Domain | "">("");
  const [ticked, setTicked] = useState<Set<string>>(new Set());

  const domainOf = useMemo(() => new Map(elementTypes.map((t) => [t.id, t.domain])), [elementTypes]);
  const wanted = useMemo(() => (tree ? placesOfNodeIds(componentNodeIds, tree) : []), [tree, componentNodeIds]);
  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return candidates.filter((e) => {
      if (wanted.length > 0) {
        const own = places[e.id] ?? [];
        const inWanted = wanted.some((w) => own.some((p) => (w.category_id ? p.category_id === w.category_id : p.component_id === w.component_id)));
        if (!inWanted) return false;
      }
      if (typeId && e.element_type_id !== typeId) return false;
      if (domain && domainOf.get(e.element_type_id) !== domain && domainOf.get(e.element_type_id) !== "any") return false;
      return !needle || `${e.unique_code} ${e.name} ${e.element_type_name}`.toLowerCase().includes(needle);
    });
  }, [candidates, search, typeId, domain, domainOf, wanted, places]);
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
          {tree && tree.components.length > 0 && (
            <div className="stack" style={{ gap: "var(--space-1)", minWidth: "14rem" }}>
              <FieldCaption label={strings.placements.filterLabel} help={strings.help.recordComponentsFilter} />
              <TreeSelect
                triggerLabel={strings.placements.filterLabel} emptyLabel={strings.placements.choose} nodes={placementNodes(tree)}
                selectedIds={componentNodeIds} onChange={setComponentNodeIds} searchable
              />
            </div>
          )}
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
