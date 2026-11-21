/**
 * Module: components/TagCreateModal
 *
 * The dialog that adds a tag to a vocabulary, opened by the Tags page's "New tag" button so the page shows no empty
 * fields until someone asks (docs/ux-style-guide.md, "Pattern: creation controls on demand").
 *
 * Responsibilities:
 * - Collect the tag's name (validated with `tagNameProblem`, the server's rule) and optional colour.
 * - Hand them to `onCreate`; a refusal stays in the dialog beside Save and the dialog closes only once the tag exists.
 *
 * The caller's `onCreate` reloads the vocabulary and shows the toast.
 */
import { useState } from "react";

import { TAG_NAME_MAX_LENGTH, tagNameProblem } from "../api/tags";
import { useStrings } from "../context/TerminologyContext";
import { toErrorMessage } from "../context/ToastContext";
import { ColorField, TextField } from "./FormFields";
import { FormActions } from "./FormActions";
import { Modal } from "./Modal";
import { TAG_COLOURS } from "./tagColours";

/**
 * @param onCreate Adds the tag; `colour` is `null` for none. A rejection is shown in the dialog.
 * @param onClose Closes the dialog; called after a successful add and by the close button.
 */
export function TagCreateModal({
  onCreate, onClose,
}: {
  onCreate: (name: string, colour: string | null) => Promise<void>;
  onClose: () => void;
}) {
  const strings = useStrings();
  const text = strings.tags.admin;
  const [name, setName] = useState("");
  const [colour, setColour] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const problem = name.trim() === "" ? null : tagNameProblem(name);
  const valid = name.trim() !== "" && !problem;

  async function save() {
    if (!valid || busy) return;
    setBusy(true);
    setError(null);
    try {
      await onCreate(name.trim(), colour || null);
      onClose();
    } catch (err) {
      setError(toErrorMessage(err, strings.common.error));
      setBusy(false);
    }
  }

  return (
    <Modal title={text.addLabel} onClose={onClose}>
      <form className="stack" onSubmit={(e) => { e.preventDefault(); void save(); }}>
        <TextField helpNotNeeded required
          label={text.addNameLabel}
          value={name}
          onChange={setName}
          inputProps={{ maxLength: TAG_NAME_MAX_LENGTH * 2, autoFocus: true }}
        />
        {problem && (
          <span role="alert" style={{ fontSize: "0.8rem", color: "var(--color-danger)" }}>
            {problem === "too_long" ? strings.tags.tooLong(TAG_NAME_MAX_LENGTH) : strings.tags.invalidCharacters}
          </span>
        )}
        <ColorField help={strings.help.tagColour}
          label={text.colourHeading}
          value={colour}
          onChange={setColour}
          presets={TAG_COLOURS}
          emptyLabel={text.noColour}
        />
        <FormActions error={error} onCancel={onClose} onSave={() => void save()} saveLabel={text.addButton} saveDisabled={!valid || busy} />
      </form>
    </Modal>
  );
}
