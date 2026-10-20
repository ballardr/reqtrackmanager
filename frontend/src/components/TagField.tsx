/**
 * Module: components/TagField
 *
 * The "Tags" field of a create form: choose the tags the new record starts with. Nothing is
 * written here; the form applies them with `useCommitTags` once the record exists, the same
 * contract as `QuickLinkField`.
 *
 * It asks the server about a record that does not exist yet (`DRAFT_ARTEFACT_ID`), so the
 * vocabulary, the project's mode and the caller's authority are the ones that will apply, and it
 * renders nothing when the caller may not tag this kind of record or the read fails: a form never
 * offers a field that would be refused.
 */
import { useEffect, useState } from "react";

import { DRAFT_ARTEFACT_ID } from "../api/artefactLinks";
import { recordTagsApi, type RecordTags, type RecordTagsApi } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { TagInput } from "./TagInput";

/**
 * @param projectId The project the record is being created in.
 * @param artefactType The registered type of the record being created.
 * @param value The tag names chosen so far; the form owns them.
 * @param onChange Called with the new list.
 * @param api Injectable calls (stories pass a fake).
 */
export function TagField({
  projectId, artefactType, value, onChange, api = recordTagsApi,
}: {
  projectId: string;
  artefactType: string;
  value: string[];
  onChange: (names: string[]) => void;
  api?: RecordTagsApi;
}) {
  const strings = useStrings();
  const [data, setData] = useState<RecordTags | null>(null);

  useEffect(() => {
    let active = true;
    api.get(projectId, artefactType, DRAFT_ARTEFACT_ID)
      .then((result) => active && setData(result))
      .catch(() => active && setData(null));
    return () => {
      active = false;
    };
  }, [api, projectId, artefactType]);

  if (!data || !data.can_edit) return null;
  return (
    <div className="stack" style={{ gap: "0.25rem" }}>
      <span>{strings.tags.label}</span>
      <TagInput value={value} onChange={onChange} suggestions={data.suggestions} restricted={data.restricted} />
      <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.tags.create.hint}</span>
    </div>
  );
}
