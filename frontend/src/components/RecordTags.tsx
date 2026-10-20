/**
 * Module: components/RecordTags
 *
 * The tags of one existing record, in its header: chips for everyone who can open the record,
 * and, for someone who may tag it, the tag picker so a tag is added or removed in place.
 *
 * Responsibilities:
 * - Load the record's tags, the vocabulary to pick from, the project's mode and `can_edit`
 *   in one read (`RecordTagsApi.get`).
 * - Save every change at once (the whole set, `RecordTagsApi.set`), showing the change
 *   straight away and putting it back with an error toast if the server refuses.
 * - Say nothing when the record has no tags and the viewer cannot add any.
 *
 * `onChanged` lets a page refresh anything that shows the tags' effects (the Activity tab).
 * `api` is injectable for stories.
 */
import { useEffect, useRef, useState } from "react";

import { recordTagsApi, type RecordTags as RecordTagsData, type RecordTagsApi } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage, useToast } from "../context/ToastContext";
import { TagChip } from "./TagChip";
import { TagInput } from "./TagInput";

/**
 * @param projectId The project the page is opened in.
 * @param artefactType The record's registered artefact type.
 * @param artefactId The record's id.
 * @param onChanged Called after a change was saved.
 * @param api The calls (the live ones by default).
 */
export function RecordTags({
  projectId, artefactType, artefactId, onChanged, api = recordTagsApi,
}: {
  projectId: string;
  artefactType: string;
  artefactId: string;
  onChanged?: () => void;
  api?: RecordTagsApi;
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
      <div className="row" style={{ gap: "0.35rem" }} aria-label={strings.tags.label} role="group">
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
