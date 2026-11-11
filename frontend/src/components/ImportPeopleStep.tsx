/**
 * Module: components/ImportPeopleStep
 *
 * The People step of a bundle import: each person the bundle names, how the import will record them (a matched
 * member, an imported person, the importer, or a reassigned member), and a choice per person to change that.
 *
 * Responsibilities: draw the table and the "keep original email" switch and report the importer's choices
 * upward. It reads the preview and holds nothing itself; `BundleImportDialog` fetches the preview and passes the
 * choices to the import request.
 *
 * Design: the choices are the request's `people` field (`ImportPeopleChoices`); an absent mapping entry means
 * Automatic. A person shown as an imported person is badged, so the importer sees who will not be a member.
 */
import { useMemo } from "react";

import type { ImportedPerson, ImportPeopleChoices } from "../api/types";
import { IMPORTED_PERSON_RESOLUTION_LABEL, IMPORTED_PERSON_RESOLUTION_TONE } from "../api/types";
import { useStrings } from "../context/TerminologyContext";
import { Badge } from "./Badge";
import { FieldHelp } from "./FieldHelp";
import { CheckboxField } from "./FormFields";
import { InlineSelect } from "./LabeledSelect";

/** A member of the importing organisation the importer may reassign a person to. */
export interface ImportMemberOption {
  user_id: string;
  display_name: string;
}

const AUTOMATIC = "";
const STAND_IN = "stand_in";
const ME = "me";

/**
 * @param people The preview: each person in the bundle and their current resolution.
 * @param members The importing organisation's members, offered as reassignment targets.
 * @param choices The importer's decisions so far.
 * @param onChange Called with the new decisions.
 * @param loading True while the preview is being read.
 * @param error A message when the preview could not be read.
 */
export function ImportPeopleStep({
  people, members, choices, onChange, loading = false, error = null,
}: {
  people: readonly ImportedPerson[];
  members: readonly ImportMemberOption[];
  choices: ImportPeopleChoices;
  onChange: (choices: ImportPeopleChoices) => void;
  loading?: boolean;
  error?: string | null;
}) {
  const strings = useStrings();
  const text = strings.importPeople;
  const options = useMemo(
    () => [
      { value: AUTOMATIC, label: text.choiceAutomatic },
      { value: STAND_IN, label: text.choiceImportedPerson },
      { value: ME, label: text.choiceMe },
      ...members.map((m) => ({ value: m.user_id, label: m.display_name })),
    ],
    [members, text],
  );

  function choose(email: string, value: string) {
    const mapping = { ...choices.mapping };
    if (value === AUTOMATIC) delete mapping[email];
    else mapping[email] = value;
    onChange({ ...choices, mapping });
  }

  if (loading) return <p className="text-muted" role="status">{text.loading}</p>;
  if (error) return <p role="alert" style={{ color: "var(--color-danger)" }}>{error}</p>;
  if (people.length === 0) return <p className="text-muted">{text.none}</p>;
  return (
    <div className="stack" data-testid="import-people-step">
      <table className="table" aria-label={text.heading}>
        <thead>
          <tr>
            <th scope="col">{text.columnPerson}</th>
            <th scope="col">{text.columnResult}</th>
            <th scope="col"><span className="row" style={{ gap: "var(--space-2)" }}>{text.columnChoice}<FieldHelp label={text.columnChoice} help={strings.help.importPeople} /></span></th>
          </tr>
        </thead>
        <tbody>
          {people.map((p) => (
            <tr key={p.email}>
              <td>
                <div>{p.display_name}</div>
                <div className="text-muted" style={{ fontSize: "0.8rem" }}>{p.email}</div>
              </td>
              <td>
                <Badge tone={IMPORTED_PERSON_RESOLUTION_TONE[p.resolution]}>
                  {p.member_name && p.resolution !== "stand_in" ? `${IMPORTED_PERSON_RESOLUTION_LABEL[p.resolution]}: ${p.member_name}` : IMPORTED_PERSON_RESOLUTION_LABEL[p.resolution]}
                </Badge>
              </td>
              <td>
                <InlineSelect
                  ariaLabel={text.choiceLabel(p.display_name)} placeholder={null} autoWidth
                  value={choices.mapping[p.email] ?? AUTOMATIC} onChange={(v) => choose(p.email, v)} options={options}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <CheckboxField
        label={text.keepOriginalEmail} checked={choices.keep_original_email}
        onChange={(checked) => onChange({ ...choices, keep_original_email: checked })}
        help={strings.help.keepOriginalEmail}
      />
    </div>
  );
}
