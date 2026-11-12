/**
 * Module: modules/architecture/NewElementDialog
 *
 * The small prompt shown when an element type is dropped (or pressed) in the editor: the new element's name. The element is
 * created as a Draft of the chosen type, inside the diagram's scope element when it has one (so it appears among the scope's
 * children), and the editor places it where it was dropped. The full form (description, owner, ports, tags) is the
 * element's own page.
 */
import { useState } from "react";

import { FormActions } from "../../components/FormActions";
import { TextField } from "../../components/FormFields";
import { Modal } from "../../components/Modal";

/**
 * @param typeName The chosen type's name, shown in the title.
 * @param error A save error to show.
 * @param onCreate Called with the trimmed name.
 */
export function NewElementDialog({
  typeName, error, onCancel, onCreate,
}: {
  typeName: string;
  error?: string | null;
  onCancel: () => void;
  onCreate: (name: string) => void;
}) {
  const [name, setName] = useState("");
  return (
    <Modal title={`New ${typeName}`} onClose={onCancel}>
      <div className="stack">
        <TextField helpNotNeeded required label="Name" value={name} onChange={setName} />
        <FormActions error={error} onCancel={onCancel} onSave={() => onCreate(name.trim())} saveDisabled={name.trim() === ""} />
      </div>
    </Modal>
  );
}
