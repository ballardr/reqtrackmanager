/**
 * Module: hooks/useRecordLabels
 *
 * The three sets of labels one existing record carries, each read and saved on its own endpoint: its tags, its places in
 * the component tree and its external references. `RecordTags` (the record header's one chip row) draws all three through
 * these hooks, so the load, the optimistic change and the refusal handling live once and the component only lays out.
 *
 * Responsibilities:
 * - Load each set (and what its editor needs: the tag vocabulary, the project's tree, the systems) when the record changes.
 * - Save every tag or place change at once (the whole set), showing it straight away and putting it back with an error
 *   toast if the server refuses; add, change and remove one reference, each ending in a toast.
 * - Show nothing for a failed read: a label is secondary to the record, so an error is not shown in its header.
 *
 * Design decisions: `enabled` turns a read off (a type with no component tree, a page that keeps its own references)
 * without a conditional hook call. `reload` re-reads all three after a change made elsewhere.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import {
  recordReferencesApi, type ExternalReference, type RecordReferences as ReferencesData, type RecordReferencesApi,
} from "../api/externalReferences";
import {
  recordPlacementsApi, type PlacementPair, type PlacementTree, type RecordPlacements as PlacementsData, type RecordPlacementsApi,
} from "../api/placements";
import { recordTagsApi, type RecordTags as TagsData, type RecordTagsApi } from "../api/tags";
import { referenceInput, type ReferenceDraft } from "../components/referenceDraft";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";

/** Which record the hooks read. */
export interface RecordRef {
  projectId: string;
  artefactType: string;
  artefactId: string;
}

/**
 * The record's tags.
 *
 * @param record The record.
 * @param onChanged Called after a change was saved.
 * @param api The tag calls (the live ones by default).
 * @returns `data` (null until read, or when the read failed) and `change(names)`, which saves the whole set.
 */
export function useRecordTagSet(record: RecordRef, onChanged?: () => void, api: RecordTagsApi = recordTagsApi) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [data, setData] = useState<TagsData | null>(null);
  const saving = useRef(0);
  const { projectId, artefactType, artefactId } = record;

  useEffect(() => {
    let active = true;
    api.get(projectId, artefactType, artefactId)
      .then((result) => active && setData(result))
      .catch(() => active && setData(null));
    return () => {
      active = false;
    };
  }, [api, projectId, artefactType, artefactId]);

  const change = useCallback(async (names: string[]) => {
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
  }, [api, artefactId, artefactType, data, onChanged, projectId, showToast, strings]);

  return { data, change };
}

/**
 * The record's places in the component tree.
 *
 * @param record The record.
 * @param enabled False skips the read (a type that cannot be placed).
 * @param onChanged Called after a change was saved.
 * @param api The calls (the live ones by default).
 * @returns `data`, the project's `tree` (only for someone who may place the record) and `change(pairs)`.
 */
export function useRecordPlaceSet(
  record: RecordRef, enabled: boolean, onChanged?: () => void, api: RecordPlacementsApi = recordPlacementsApi,
) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [data, setData] = useState<PlacementsData | null>(null);
  const [tree, setTree] = useState<PlacementTree | null>(null);
  const saving = useRef(0);
  const { projectId, artefactType, artefactId } = record;

  useEffect(() => {
    if (!enabled) return undefined;
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
  }, [api, enabled, projectId, artefactType, artefactId]);

  const change = useCallback(async (chosen: PlacementPair[]) => {
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
  }, [api, artefactId, artefactType, data, onChanged, projectId, showToast, strings, tree]);

  return { data: enabled ? data : null, tree: enabled ? tree : null, change };
}

/**
 * The record's external references.
 *
 * @param record The record.
 * @param enabled False skips the read (a page that keeps its own references).
 * @param onChanged Called after a change was saved.
 * @param api The calls (the live ones by default).
 * @returns `data`, `save(existing, draft)` (adds when `existing` is null; throws the server's error so the dialog can show
 *   it) and `remove(reference)` (ends in a toast either way).
 */
export function useRecordReferenceSet(
  record: RecordRef, enabled: boolean, onChanged?: () => void, api: RecordReferencesApi = recordReferencesApi,
) {
  const strings = useStrings();
  const { showToast } = useToast();
  const [data, setData] = useState<ReferencesData | null>(null);
  const { projectId, artefactType, artefactId } = record;

  useEffect(() => {
    if (!enabled) return undefined;
    let active = true;
    api.get(projectId, artefactType, artefactId)
      .then((result) => active && setData(result))
      .catch(() => active && setData(null));
    return () => {
      active = false;
    };
  }, [api, enabled, projectId, artefactType, artefactId]);

  const save = useCallback(async (existing: ExternalReference | null, draft: ReferenceDraft) => {
    const body = referenceInput(draft);
    const saved = existing === null
      ? await api.add(projectId, artefactType, artefactId, body)
      : await api.update(projectId, artefactType, artefactId, existing.id, body);
    setData(saved);
    showToast(existing === null ? strings.references.added : strings.references.updated, "success");
    onChanged?.();
  }, [api, artefactId, artefactType, onChanged, projectId, showToast, strings]);

  const remove = useCallback(async (reference: ExternalReference) => {
    try {
      setData(await api.remove(projectId, artefactType, artefactId, reference.id));
      showToast(strings.references.removed, "success");
      onChanged?.();
    } catch (err) {
      showToast(strings.references.removeFailed(toErrorMessage(err, strings.common.error)), "error");
    }
  }, [api, artefactId, artefactType, onChanged, projectId, showToast, strings]);

  return { data: enabled ? data : null, save, remove };
}
