/**
 * Module: modules/architecture/ElementFormModal
 *
 * Create and edit dialog for an element, shared by the Elements list (create), the detail page (edit), the Links
 * panel's "Create new" and the organisation's own elements, and told apart by whether `initial` is passed. Both modes
 * take the same `ElementFields`; only a new element also takes ports (an existing element's ports are edited on its
 * page, one change at a time), quick links, tags and "Save and activate" (an element has no approval step, so activating
 * needs only the permission to create). An organisation-owned element has no project, so it takes no links or tags.
 */
import { useState } from "react";

import type { CollectedLink } from "../../api/artefactLinks";
import type { OrgUser } from "../../api/types";
import { FormActions } from "../../components/FormActions";
import { FormGrid, FormGridFull } from "../../components/FormGrid";
import { Modal } from "../../components/Modal";
import { QuickLinkField } from "../../components/QuickLinkField";
import { TagField } from "../../components/TagField";
import { blankElementValues, subtreeIds, valuesFromElement } from "./architectureFields";
import { ElementFields } from "./ElementFields";
import { ARCHITECTURE_HELP } from "./help";
import { PortList, type PortRow } from "./PortList";
import { FieldCaption } from "../../components/FieldHelp";
import type {
  ArchitectureElement, ArchitectureSymbol, ConnectionType, ElementFieldValues, ElementType, PortValues,
} from "./types";

/** What a new element takes beyond the shared fields. */
export interface ElementCreateExtras {
  ports: PortValues[];
  activate: boolean;
  quickLinks: CollectedLink[];
  tags: string[];
}

/**
 * @param initial The element being edited; omit to create.
 * @param elementTypes The types that may be chosen.
 * @param connectionTypes The connection types a new port may name.
 * @param candidates The owner's elements, from which the parent choices are taken.
 * @param symbols The symbols that may be chosen.
 * @param symbolUrl The API path of a symbol's content.
 * @param orgUsers Organisation members offered as owner.
 * @param organizationId The owning organisation.
 * @param projectId The owning project; omit for an organisation element (no links, tags or project groups).
 * @param defaultParentId A parent to preselect for a new element (the element it is added under).
 * @param error A save error to show.
 * @param onSave Called with the values and, for a new element, the extras.
 */
export function ElementFormModal({
  initial, elementTypes, connectionTypes, candidates, symbols, symbolUrl, orgUsers, organizationId, projectId,
  defaultParentId = null, error, onCancel, onSave,
}: {
  initial?: ArchitectureElement;
  elementTypes: ElementType[];
  connectionTypes: ConnectionType[];
  candidates: ArchitectureElement[];
  symbols: ArchitectureSymbol[];
  symbolUrl: (symbolId: string) => string;
  orgUsers: OrgUser[];
  organizationId: string;
  projectId?: string;
  defaultParentId?: string | null;
  error?: string | null;
  onCancel: () => void;
  onSave: (values: ElementFieldValues, extras: ElementCreateExtras) => void;
}) {
  const [values, setValues] = useState<ElementFieldValues>(() =>
    initial ? valuesFromElement(initial) : blankElementValues(elementTypes[0]?.id ?? "", defaultParentId));
  const [ports, setPorts] = useState<PortRow[]>([]);
  const [quickLinks, setQuickLinks] = useState<CollectedLink[]>([]);
  const [tags, setTags] = useState<string[]>([]);
  const set = <K extends keyof ElementFieldValues>(key: K, value: ElementFieldValues[K]) =>
    setValues((prev) => ({ ...prev, [key]: value }));

  const excluded = initial ? subtreeIds(initial.id, candidates) : new Set<string>();
  const parents = candidates.filter((e) => !excluded.has(e.id) && e.status !== "retired");
  const valid = values.name.trim() !== "" && values.element_type_id !== "";

  function save(activate: boolean) {
    onSave(
      { ...values, name: values.name.trim() },
      { ports: ports.map(({ name, direction, connection_type_id }) => ({ name, direction, connection_type_id })), activate, quickLinks, tags },
    );
  }

  return (
    <Modal title={initial ? `Edit ${initial.name}` : "New element"} onClose={onCancel} size="lg">
      <div className="stack">
        <FormGrid minColumn="18rem">
          <ElementFields
            values={values} onChange={set} elementTypes={elementTypes} parents={parents} symbols={symbols} symbolUrl={symbolUrl}
            orgUsers={orgUsers} organizationId={organizationId} projectId={projectId} saved={initial}
          />
          {!initial && (
            <FormGridFull>
              <div className="stack" style={{ gap: "var(--space-1)" }}>
                <FieldCaption label="Ports" help={ARCHITECTURE_HELP.elementPorts} />
                <PortList
                  ports={ports} connectionTypes={connectionTypes}
                  onAdd={async (port) => setPorts((prev) => [...prev, { id: `new-${prev.length}-${Date.now()}`, ...port }])}
                  onChange={async (id, change) => setPorts((prev) => prev.map((p) => (p.id === id ? { ...p, ...change } : p)))}
                  onRemove={async (id) => setPorts((prev) => prev.filter((p) => p.id !== id))}
                />
              </div>
            </FormGridFull>
          )}
          {!initial && projectId && (
            <FormGridFull>
              <div className="stack">
                <QuickLinkField projectId={projectId} artefactType="architecture_element" value={quickLinks} onChange={setQuickLinks} />
                <TagField projectId={projectId} artefactType="architecture_element" value={tags} onChange={setTags} />
              </div>
            </FormGridFull>
          )}
        </FormGrid>
        <FormActions
          error={error} onCancel={onCancel} onSave={() => save(false)} saveDisabled={!valid}
          onSaveAndActivate={initial ? undefined : () => save(true)}
        />
      </div>
    </Modal>
  );
}
