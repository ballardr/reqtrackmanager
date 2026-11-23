/**
 * Module: components/RecordTags
 *
 * The labels of one existing record, in its header or a side panel: one row of chips (each tag, each place in the
 * component tree, each external reference) followed by one (+) button whose menu names what it adds: Add tag, Add
 * component or category, Add external reference. Every page that shows a record's tags shows components and
 * references the same way.
 *
 * - Reads the three sets through `useRecordLabels` and draws them as tags, components, references, each chip with
 *   its own remove (and, for a reference, edit) control for someone who may change it.
 * - A menu row appears only for what the person may do: tags and places need the record's edit right (places also a
 *   project with components and a record that keeps no component of its own), references need a system to exist. A
 *   row that does not apply is absent, never disabled, and with no row the (+) is not drawn.
 * - Editors: the shared `TagAddBox` in a popover at the (+), the `PlacementPicker` in a dialog (a tree picker is a
 *   popover and popovers do not nest) and the `ReferenceFormModal`.
 * - Nothing is drawn for a record with no labels that the viewer cannot add to, or for a failed read.
 *
 * One form with no compact variant, so the header and a side panel cannot drift; the row wraps, keeping the (+)
 * after the last chip. `components` and `references` leave out a kind the page keeps elsewhere. `onChanged` lets a
 * page refresh anything showing the change (the Activity tab). The three `*Api` props are injectable for stories.
 */
import { Boxes, Plus } from "lucide-react";
import { useRef, useState } from "react";

import { referenceLabel, recordReferencesApi, type ExternalReference, type RecordReferencesApi } from "../api/externalReferences";
import { placementLabel, recordPlacementsApi, type RecordPlacementsApi } from "../api/placements";
import { recordTagsApi, type RecordTagsApi } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { useRecordPlaceSet, useRecordReferenceSet, useRecordTagSet } from "../hooks/useRecordLabels";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";
import { ConfirmDialog } from "./ConfirmDialog";
import { FieldCaption } from "./FieldHelp";
import { Modal } from "./Modal";
import { PlacementPicker } from "./PlacementPicker";
import { Popover } from "./Popover";
import { ReferenceChip } from "./ReferenceChip";
import { ReferenceFormModal } from "./ReferenceFormModal";
import { RemovableChip } from "./RemovableChip";
import { TagAddBox } from "./TagAddBox";
import { TagChip } from "./TagChip";
import { Tooltip } from "./Tooltip";

/**
 * @param projectId The project the page is opened in.
 * @param artefactType The record's registered artefact type.
 * @param artefactId The record's id.
 * @param onChanged Called after a change was saved.
 * @param api The tag calls (the live ones by default).
 * @param placementsApi The component calls (the live ones by default).
 * @param components False leaves out the components, for a type that cannot be placed in the component tree.
 * @param references False leaves out the external references, for a page that keeps its own (a Product Feedback request).
 * @param referencesApi The external reference calls (the live ones by default).
 */
export function RecordTags({
  projectId, artefactType, artefactId, onChanged, api = recordTagsApi, placementsApi = recordPlacementsApi,
  components = true, references = true, referencesApi = recordReferencesApi,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  onChanged?: () => void;
  api?: RecordTagsApi;
  placementsApi?: RecordPlacementsApi;
  components?: boolean;
  references?: boolean;
  referencesApi?: RecordReferencesApi;
}) {
  const strings = useStrings();
  const record = { projectId, artefactType, artefactId };
  const tagSet = useRecordTagSet(record, onChanged, api);
  const placeSet = useRecordPlaceSet(record, components, onChanged, placementsApi);
  const referenceSet = useRecordReferenceSet(record, references, onChanged, referencesApi);
  const [adding, setAdding] = useState<"tag" | "place" | null>(null);
  const [editing, setEditing] = useState<ExternalReference | "new" | null>(null);
  const [removing, setRemoving] = useState<ExternalReference | null>(null);
  const [error, setError] = useState<string | null>(null);
  const addRef = useRef<HTMLSpanElement>(null);

  const tags = tagSet.data;
  const places = placeSet.data && !placeSet.data.managed_on_record ? placeSet.data.placements : [];
  const refs = referenceSet.data;
  const canTag = !!tags?.can_edit;
  const canPlace = !!placeSet.data?.can_edit && !placeSet.data.managed_on_record && !!placeSet.tree && placeSet.tree.components.length > 0;
  const canReference = !!refs?.can_edit && refs.systems.length > 0;
  const canChangeReferences = !!refs?.can_edit;
  const chipCount = (tags?.tags.length ?? 0) + places.length + (refs?.references.length ?? 0);
  if (chipCount === 0 && !canTag && !canPlace && !canReference) return null;

  const text = strings.tags;
  const candidates: Array<ActionMenuItem | false> = [
    canTag && { label: text.addTag, key: "tag", onSelect: () => setAdding("tag") },
    canPlace && { label: text.addPlace, key: "place", onSelect: () => setAdding("place") },
    canReference && { label: strings.references.addLabel, key: "reference", onSelect: () => { setError(null); setEditing("new"); } },
  ];
  const items = candidates.filter((item): item is ActionMenuItem => !!item);

  async function saveReference(draft: Parameters<typeof referenceSet.save>[1]) {
    if (editing === null) return;
    setError(null);
    try {
      await referenceSet.save(editing === "new" ? null : editing, draft);
      setEditing(null);
    } catch (err) {
      setError(strings.references.saveFailed(err instanceof Error ? err.message : strings.common.error));
    }
  }

  return (
    <>
      <div className="row" style={{ gap: "var(--space-2)", flexWrap: "wrap", alignItems: "center", minWidth: 0 }} role="group" aria-label={text.groupLabel}>
        {tags?.tags.map((tag) => (
          <TagChip
            key={tag.id} tag={tag} removeLabel={text.removeLabel(tag.name)}
            onRemove={canTag ? () => tagSet.change((tags?.tags ?? []).filter((t) => t.id !== tag.id).map((t) => t.name)) : undefined}
          />
        ))}
        {places.map((place) => (
          <Tooltip key={`${place.component_id}:${place.category_id}`} label={text.placeKind}>
            <RemovableChip
              icon={<Boxes size={12} aria-hidden="true" />}
              label={placementLabel(place)}
              removeLabel={strings.placements.removeLabel(placementLabel(place))}
              onRemove={canPlace
                ? () => placeSet.change(places.filter((p) => p.component_id !== place.component_id || p.category_id !== place.category_id))
                : undefined}
            />
          </Tooltip>
        ))}
        {refs?.references.map((reference) => (
          <ReferenceChip
            key={reference.id} reference={reference}
            onEdit={canChangeReferences ? () => { setError(null); setEditing(reference); } : undefined}
            onRemove={canChangeReferences ? () => setRemoving(reference) : undefined}
          />
        ))}
        {items.length > 0 && (
          <span ref={addRef} style={{ display: "inline-flex" }}>
            <ActionMenu triggerLabel={text.addMenuLabel} icon={<Plus size={14} aria-hidden="true" />} size="sm" items={items} />
          </span>
        )}
      </div>
      {adding === "tag" && tags && (
        <Popover anchorRef={addRef} title={text.addTag} onClose={() => setAdding(null)} fit>
          <TagAddBox
            value={tags.tags.map((t) => t.name)} onChange={tagSet.change} suggestions={tags.suggestions}
            restricted={tags.restricted} onDone={() => setAdding(null)}
          />
        </Popover>
      )}
      {adding === "place" && placeSet.tree && (
        <Modal title={text.addPlace} onClose={() => setAdding(null)}>
          <div className="stack" style={{ gap: "var(--space-1)" }}>
            <FieldCaption label={strings.placements.label} help={strings.placements.help} />
            <PlacementPicker tree={placeSet.tree} value={places} onChange={placeSet.change} />
          </div>
        </Modal>
      )}
      {editing !== null && refs && (
        <ReferenceFormModal
          initial={editing === "new" ? undefined : editing} systems={refs.systems} error={error}
          onCancel={() => setEditing(null)} onSave={saveReference}
        />
      )}
      {removing && (
        <ConfirmDialog
          title={strings.references.removeTitle} message={strings.references.removeMessage(referenceLabel(removing))}
          confirmLabel={strings.references.removeConfirm}
          onConfirm={() => { const target = removing; setRemoving(null); void referenceSet.remove(target); }}
          onCancel={() => setRemoving(null)}
        />
      )}
    </>
  );
}
