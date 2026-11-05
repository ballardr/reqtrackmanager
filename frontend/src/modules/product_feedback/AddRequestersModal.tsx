/**
 * Module: modules/product_feedback/AddRequestersModal
 *
 * Adds requesters to a saved request from the Demand card: the shared `RequestersField` in a dialog, saved as
 * "Requested by" links. Saving is the page's (it creates the links and reloads the demand); the dialog only collects
 * the choice, so it is the same field the create and edit forms show.
 */
import { useState } from "react";

import type { ArtefactLinksApi, CollectedLink } from "../../api/artefactLinks";
import { FormActions } from "../../components/FormActions";
import { Modal } from "../../components/Modal";
import { RequestersField } from "./RequestersField";

/**
 * @param projectId The request's project.
 * @param onCancel Closes the dialog.
 * @param onSave Called with the chosen requesters; the caller closes the dialog when they were added.
 * @param api Injectable link calls (stories pass a fake).
 */
export function AddRequestersModal({
  projectId, onCancel, onSave, api,
}: { projectId: string; onCancel: () => void; onSave: (links: CollectedLink[]) => void | Promise<void>; api?: ArtefactLinksApi }) {
  const [links, setLinks] = useState<CollectedLink[]>([]);
  return (
    <Modal title="Add requesters" onClose={onCancel}>
      <div className="stack">
        <RequestersField projectId={projectId} value={links} onChange={setLinks} api={api} help="Each is recorded with “Requested by”." />
        <FormActions onCancel={onCancel} onSave={() => void onSave(links)} saveDisabled={links.length === 0} />
      </div>
    </Modal>
  );
}
