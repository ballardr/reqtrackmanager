/**
 * Module: components/RecordTags
 *
 * The tags of one existing record, in its header: chips for everyone who can open the record,
 * and, for someone who may tag it, the tag picker so a tag is added or removed in place. The record's components
 * (`RecordPlacements`) are shown beside them, so every page that shows tags shows places too.
 *
 * Responsibilities:
 * - Load the record's tags, the vocabulary to pick from, the project's mode and `can_edit`
 *   in one read (`RecordTagsApi.get`).
 * - Save every change at once (the whole set, `RecordTagsApi.set`), showing the change
 *   straight away and putting it back with an error toast if the server refuses.
 * - Say nothing when the record has no tags and the viewer cannot add any.
 *
 * `inline` is the compact form for the header's badge line (`RecordHeader` `tagsInline`): the tags and components as
 * read-only chips, nothing at all for a record with neither, and, for someone who may change them, one small
 * "Tags and components" button that opens the full editor in a dialog (a tag picker and a component picker each open
 * a popover of their own, and popovers do not nest). The chips follow each change made in the dialog.
 *
 * `onChanged` lets a page refresh anything that shows the tags' effects (the Activity tab).
 * `api` and `placementsApi` are injectable for stories.
 */
import { Tags } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { placementLabel, recordPlacementsApi, type RecordPlacements as PlacementsData, type RecordPlacementsApi } from "../api/placements";
import { recordTagsApi, type RecordTags as RecordTagsData, type RecordTagsApi } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { Modal } from "./Modal";
import { RecordPlacements } from "./RecordPlacements";
import { TagChip } from "./TagChip";
import { TagInput } from "./TagInput";
import { Tooltip } from "./Tooltip";

/**
 * @param projectId The project the page is opened in.
 * @param artefactType The record's registered artefact type.
 * @param artefactId The record's id.
 * @param onChanged Called after a change was saved.
 * @param inline The compact form for the header's badge line (see the module note).
 * @param api The tag calls (the live ones by default).
 * @param placementsApi The component calls (the live ones by default).
 */
export function RecordTags({
  projectId, artefactType, artefactId, onChanged, inline = false, api = recordTagsApi, placementsApi = recordPlacementsApi,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  onChanged?: () => void;
  inline?: boolean;
  api?: RecordTagsApi;
  placementsApi?: RecordPlacementsApi;
}) {
  if (inline) {
    return (
      <RecordTagsInline
        projectId={projectId} artefactType={artefactType} artefactId={artefactId}
        onChanged={onChanged} api={api} placementsApi={placementsApi}
      />
    );
  }
  return (
    <>
      <RecordTagList projectId={projectId} artefactType={artefactType} artefactId={artefactId} onChanged={onChanged} api={api} />
      <RecordPlacements projectId={projectId} artefactType={artefactType} artefactId={artefactId} onChanged={onChanged} api={placementsApi} />
    </>
  );
}

/**
 * The compact form of {@link RecordTags}: read-only chips and the "Tags and components" button.
 *
 * Reads the record's tags and places itself (the dialog's editor loads its own copy), so it shows each change the
 * dialog saves. A failed read shows nothing, as in the full form.
 *
 * @param props The same props as {@link RecordTags}, all required.
 */
function RecordTagsInline({
  projectId, artefactType, artefactId, onChanged, api, placementsApi,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  onChanged?: () => void;
  api: RecordTagsApi;
  placementsApi: RecordPlacementsApi;
}) {
  const strings = useStrings();
  const [tags, setTags] = useState<RecordTagsData | null>(null);
  const [places, setPlaces] = useState<PlacementsData | null>(null);
  const [editing, setEditing] = useState(false);
  const [reads, setReads] = useState(0);

  useEffect(() => {
    let active = true;
    api.get(projectId, artefactType, artefactId).then((r) => active && setTags(r)).catch(() => active && setTags(null));
    placementsApi.get(projectId, artefactType, artefactId).then((r) => active && setPlaces(r)).catch(() => active && setPlaces(null));
    return () => {
      active = false;
    };
  }, [api, placementsApi, projectId, artefactType, artefactId, reads]);

  const shownPlaces = places && !places.managed_on_record ? places.placements : [];
  const canEdit = !!tags?.can_edit || (!!places?.can_edit && !places.managed_on_record);
  if (!canEdit && (tags?.tags.length ?? 0) === 0 && shownPlaces.length === 0) return null;
  return (
    <>
      <span className="row" style={{ gap: "var(--space-2)", alignItems: "center" }}>
        {tags?.tags.map((tag) => <TagChip key={tag.id} tag={tag} />)}
        {shownPlaces.map((place) => (
          <span key={`${place.component_id}:${place.category_id}`} className="chip">{placementLabel(place)}</span>
        ))}
        {canEdit && (
          <Tooltip label={strings.tags.editLabel}>
            <button type="button" className="btn btn-sm btn-icon" aria-label={strings.tags.editLabel} aria-haspopup="dialog" onClick={() => setEditing(true)}>
              <Tags size={14} aria-hidden="true" />
            </button>
          </Tooltip>
        )}
      </span>
      {editing && (
        <Modal title={strings.tags.editLabel} onClose={() => setEditing(false)}>
          <div className="stack">
            <RecordTags
              projectId={projectId} artefactType={artefactType} artefactId={artefactId} api={api} placementsApi={placementsApi}
              onChanged={() => {
                setReads((n) => n + 1);
                onChanged?.();
              }}
            />
          </div>
        </Modal>
      )}
    </>
  );
}

/** The tag chips or tag picker of {@link RecordTags}. */
function RecordTagList({
  projectId, artefactType, artefactId, onChanged, api,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  onChanged?: () => void;
  api: RecordTagsApi;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [data, setData] = useState<RecordTagsData | null>(null);
  const saving = useRef(0);

  useEffect(() => {
    let active = true;
    api.get(projectId, artefactType, artefactId)
      .then((result) => active && setData(result))
      .catch(() => active && setData(null));
    return () => {
      active = false;
    };
  }, [api, projectId, artefactType, artefactId]);

  // Tags are secondary to the record: if they cannot be read, show none rather than an error in the header.
  if (!data) return null;
  if (!data.can_edit) {
    if (data.tags.length === 0) return null;
    return (
      <div className="row" style={{ gap: "var(--space-2)" }} aria-label={strings.tags.label} role="group">
        {data.tags.map((tag) => <TagChip key={tag.id} tag={tag} />)}
      </div>
    );
  }

  async function change(names: string[]) {
    if (!data) return;
    const before = data;
    const ticket = ++saving.current;
    // Show the change straight away; names the vocabulary does not know yet get no colour until saved.
    setData({
      ...data,
      tags: names.map((name) => data.suggestions.find((t) => t.name.toLowerCase() === name.toLowerCase())
        ?? data.tags.find((t) => t.name.toLowerCase() === name.toLowerCase())
        ?? { id: `pending-${name}`, name, colour: null }),
    });
    try {
      const saved = await api.set(projectId, artefactType, artefactId, names);
      if (ticket === saving.current) setData(saved);
      onChanged?.();
    } catch (err) {
      if (ticket === saving.current) setData(before);
      showToast(strings.tags.saveFailed(toErrorMessage(err, strings.common.error)), "error");
    }
  }

  return (
    <TagInput
      value={data.tags.map((t) => t.name)}
      onChange={change}
      suggestions={data.suggestions}
      restricted={data.restricted}
    />
  );
}
