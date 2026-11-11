/**
 * Module: components/RecordPlacements
 *
 * The components and categories of one existing record, in its header: a chip per place for everyone who can
 * open the record and, for someone who may place it, the picker so a place is added or removed in place.
 *
 * Responsibilities:
 * - Load the record's places, `can_edit` and the project's tree (`RecordPlacementsApi`).
 * - Save every change at once (the whole set), showing it straight away and putting it back with an error toast
 *   if the server refuses.
 * - Say nothing for a record that keeps its own component (a requirement), for a record with no places that the
 *   viewer cannot place, or when the read fails: a place is secondary to the record, so an error is not shown in
 *   its header.
 *
 * `RecordTags` renders it, so every page that shows a record's tags shows its places. `api` is injectable.
 */
import { useEffect, useRef, useState } from "react";

import {
  placementLabel, recordPlacementsApi, type PlacementPair, type PlacementTree, type RecordPlacements as Data,
  type RecordPlacementsApi,
} from "../api/placements";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { PlacementPicker } from "./PlacementPicker";
import { RemovableChip } from "./RemovableChip";

/**
 * @param projectId The project the page is opened in.
 * @param artefactType The record's registered artefact type.
 * @param artefactId The record's id.
 * @param onChanged Called after a change was saved.
 * @param api The calls (the live ones by default).
 */
export function RecordPlacements({
  projectId, artefactType, artefactId, onChanged, api = recordPlacementsApi,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  onChanged?: () => void;
  api?: RecordPlacementsApi;
}) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [data, setData] = useState<Data | null>(null);
  const [tree, setTree] = useState<PlacementTree | null>(null);
  const saving = useRef(0);

  useEffect(() => {
    let active = true;
    api.get(projectId, artefactType, artefactId)
      .then(async (result) => {
        const loaded = result.can_edit && !result.managed_on_record ? await api.tree(projectId) : null;
        if (active) {
          setData(result);
          setTree(loaded);
        }
      })
      .catch(() => active && setData(null));
    return () => {
      active = false;
    };
  }, [api, projectId, artefactType, artefactId]);

  if (!data || data.managed_on_record) return null;
  const places = data.placements;
  if (!data.can_edit || !tree) {
    if (places.length === 0) return null;
    return (
      <div className="row" style={{ gap: "var(--space-2)" }} role="group" aria-label={strings.placements.label}>
        {places.map((place) => <span key={`${place.component_id}:${place.category_id}`} className="chip">{placementLabel(place)}</span>)}
      </div>
    );
  }

  async function change(chosen: PlacementPair[]) {
    if (!data || !tree) return;
    const next = chosen.map(({ component_id, category_id }) => ({ component_id, category_id }));
    const before = data;
    const ticket = ++saving.current;
    const components = new Map(tree.components.map((c) => [c.id, c.name]));
    const categories = new Map(tree.categories.map((c) => [c.id, c.name]));
    setData({
      ...data,
      placements: next.map((pair) => ({
        ...pair,
        component_name: components.get(pair.component_id) ?? "",
        category_name: pair.category_id ? categories.get(pair.category_id) ?? "" : null,
      })),
    });
    try {
      const saved = await api.set(projectId, artefactType, artefactId, next);
      if (ticket === saving.current) setData(saved);
      onChanged?.();
    } catch (err) {
      if (ticket === saving.current) setData(before);
      showToast(strings.placements.saveFailed(toErrorMessage(err, strings.common.error)), "error");
    }
  }

  return (
    <div className="stack" style={{ gap: "var(--space-1)" }}>
      <div className="row" style={{ gap: "var(--space-2)", flexWrap: "wrap" }} role="group" aria-label={strings.placements.label}>
        {places.length === 0 && <span className="text-muted">{strings.placements.none}</span>}
        {places.map((place) => (
          <RemovableChip
            key={`${place.component_id}:${place.category_id}`}
            label={placementLabel(place)}
            removeLabel={strings.placements.removeLabel(placementLabel(place))}
            onRemove={() => change(places.filter((p) => p.component_id !== place.component_id || p.category_id !== place.category_id))}
          />
        ))}
      </div>
      <PlacementPicker tree={tree} value={places} onChange={change} />
    </div>
  );
}
