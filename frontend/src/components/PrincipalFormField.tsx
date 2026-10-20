/**
 * Module: components/PrincipalFormField
 *
 * A labelled "who" field for a create/edit form: the form-label caption over a `PrincipalPicker`
 * (a user, an organisation group and, when `projectId` is given, a project group). The detail-page
 * counterpart, which also has a read-only badge mode, is `RecordPrincipalField`. Every form that
 * names an owner, decision maker or assignee uses this, so the label and spacing are the same
 * everywhere.
 */
import type { ComponentProps } from "react";

import { FieldCaption } from "./FieldHelp";
import type { FieldHelpProps } from "./FieldHelp";
import { PrincipalPicker } from "./PrincipalPicker";

/**
 * @param label The visible caption (e.g. "Owner").
 * @param help The field's `(?)` help text (or `helpNotNeeded` for a self-explanatory field).
 * @param pickerProps Everything `PrincipalPicker` takes; `ariaLabel` is its accessible name.
 */
export function PrincipalFormField({
  label, help, required, ...pickerProps
}: FieldHelpProps & { label: string } & ComponentProps<typeof PrincipalPicker>) {
  return (
    <div className="stack" style={{ gap: "0.25rem" }}>
      <FieldCaption label={label} help={help} required={required} />
      <PrincipalPicker {...pickerProps} />
    </div>
  );
}
