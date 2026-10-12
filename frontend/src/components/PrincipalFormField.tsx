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

import { PrincipalPicker } from "./PrincipalPicker";

/**
 * @param label The visible caption (e.g. "Owner").
 * @param pickerProps Everything `PrincipalPicker` takes; `ariaLabel` is its accessible name.
 */
export function PrincipalFormField({ label, ...pickerProps }: { label: string } & ComponentProps<typeof PrincipalPicker>) {
  return (
    <div className="stack" style={{ gap: "0.25rem" }}>
      <span>{label}</span>
      <PrincipalPicker {...pickerProps} />
    </div>
  );
}
