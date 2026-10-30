/**
 * Module: components/ReportSnippetFields
 *
 * The fields a saved report snippet's save and edit forms share (name, description, category), so a field added later
 * reaches both. The category offers those already in use as suggestions.
 */
import { useId } from "react";

import { useStrings } from "../context/TerminologyContext";
import { TextField } from "./FormFields";

/**
 * @param name The snippet's name (required).
 * @param description One sentence about what it adds.
 * @param category The picker group; empty files it under Saved.
 * @param categories The categories already in use, offered as suggestions.
 */
export function ReportSnippetFields({
  name, description, category, categories, onName, onDescription, onCategory,
}: {
  name: string;
  description: string;
  category: string;
  categories: string[];
  onName: (value: string) => void;
  onDescription: (value: string) => void;
  onCategory: (value: string) => void;
}) {
  const strings = useStrings();
  const text = strings.reportSnippetSave;
  const listId = useId();
  return (
    <>
      <TextField required label={text.nameLabel} value={name} onChange={onName} helpNotNeeded inputProps={{ maxLength: 200 }} />
      <TextField label={text.descriptionLabel} value={description} onChange={onDescription} helpNotNeeded inputProps={{ maxLength: 500 }} />
      <TextField
        label={text.categoryLabel} value={category} onChange={onCategory} help={strings.help.reportSnippetCategory}
        placeholder={text.defaultCategory} inputProps={{ maxLength: 60, list: listId }}
      />
      <datalist id={listId}>{categories.map((c) => <option key={c} value={c} />)}</datalist>
    </>
  );
}
