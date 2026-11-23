/**
 * Module: components/TagField
 *
 * The "Tags" field of a create form: choose the tags the new record starts with. Nothing is written here; the form
 * applies them with `useCommitTags` once the record exists, the same contract as `QuickLinkField`. It also renders
 * `ComponentField`, so a create form with tags offers components too, and `useCommitTags` applies both.
 *
 * It asks the server about a record that does not exist yet (`DRAFT_ARTEFACT_ID`), so the vocabulary, mode and caller's
 * authority are those that will apply, and renders nothing when the caller may not tag this kind of record or the read
 * fails, so a form never offers a field that would be refused.
 */
import { useEffect, useState } from "react";

import { DRAFT_ARTEFACT_ID } from "../api/artefactLinks";
import { recordTagsApi, type RecordTags, type RecordTagsApi } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { ComponentField } from "./ComponentField";
import { ReferenceField } from "./ReferenceField";
import { TagInput } from "./TagInput";

/**
 * @param projectId The project the record is being created in.
 * @param artefactType The registered type of the record being created.
 * @param value The tag names chosen so far; the form owns them.
 * @param onChange Called with the new list.
 * @param api Injectable calls (stories pass a fake).
 * @param components False leaves out the component picker, for a type that cannot be placed in the component tree.
 * @param references False leaves out the external references, for a form that collects its own (Product Feedback).
 */
export function TagField({
  projectId, artefactType, value, onChange, api = recordTagsApi, components = true, references = true,
}: {
  projectId: string;
  artefactType: string;
  value: string[];
  onChange: (names: string[]) => void;
  api?: RecordTagsApi;
  components?: boolean;
  references?: boolean;
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

  return (
    <>
      {data?.can_edit && (
        <div className="stack" style={{ gap: "var(--space-1)" }}>
          <span>{strings.tags.label}</span>
          <TagInput value={value} onChange={onChange} suggestions={data.suggestions} restricted={data.restricted} />
          <span className="text-muted" style={{ fontSize: "0.8rem" }}>{strings.tags.create.hint}</span>
        </div>
      )}
      {components && <ComponentField projectId={projectId} artefactType={artefactType} />}
      {references && <ReferenceField projectId={projectId} artefactType={artefactType} />}
    </>
  );
}
