/**
 * Module: components/ReportFolderField
 *
 * The one input for the Reports picker folder a layout, a pack or a placement files a report under: a text field
 * that suggests the folders already in use (a `<datalist>`) and says when a path would be refused.
 *
 * Responsibilities: show the field with its help, suggest `suggestions`, flag a path the server would refuse (more than
 * three levels, a level or the whole path too long). Pure presentation: tidying and the server's own check stay
 * authoritative.
 */
import { useId } from "react";

import { useStrings } from "../context/TerminologyContext";
import { folderProblem } from "../utils/reportFolders";
import { TextField } from "./FormFields";

/**
 * @param value The path as typed (levels separated by `/`).
 * @param onChange Called with the new text.
 * @param suggestions Folder paths to offer (see `distinctFolders`).
 * @param label Overrides the default label.
 * @param helpKey Which help text to show (the default describes filing a report; a placement's describes moving it).
 */
export function ReportFolderField({
  value, onChange, suggestions, label, helpKey = "reportFolder",
}: { value: string; onChange: (value: string) => void; suggestions: string[]; label?: string; helpKey?: "reportFolder" | "reportPlacementFolder" }) {
  const strings = useStrings();
  const listId = useId();
  const problem = folderProblem(value);
  return (
    <>
      <TextField
        label={label ?? strings.reportFolders.folderLabel}
        help={strings.help[helpKey]}
        value={value}
        onChange={onChange}
        placeholder={strings.reportFolders.folderPlaceholder}
        hint={problem ? <span role="alert">{problem}</span> : strings.reportFolders.folderHint}
        inputProps={{ list: listId, maxLength: 160 }}
      />
      <datalist id={listId}>
        {suggestions.map((path) => <option key={path} value={path} />)}
      </datalist>
    </>
  );
}
