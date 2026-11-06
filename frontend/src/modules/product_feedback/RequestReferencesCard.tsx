/**
 * Module: modules/product_feedback/RequestReferencesCard
 *
 * A request's external references: the items in outside tools (Jira, ServiceNow, ...) it came from or is delivered in,
 * each with its system, key, role and (for an http or https link only) a link that opens in a new tab. A triager can
 * add, change and remove them; everyone else reads. A reference is not a version of the request, so changing one
 * does not touch the version history.
 *
 * The link is user content, so it is rendered as a clickable link only when it is an absolute http(s) URL (the server
 * enforces the same rule on save; this also covers anything stored before it did) and always with `rel="noopener noreferrer"`.
 */
import { Pencil, Trash2 } from "lucide-react";

import { Badge } from "../../components/Badge";
import { DetailCard } from "../../components/DetailCard";
import { isWebUrl } from "./referenceDraft";
import { EXTERNAL_REF_ROLE_LABEL, type ExternalRef } from "./types";

/**
 * @param references The request's references.
 * @param canEdit Whether the viewer may add, change and remove them (a triager, on an unarchived request).
 * @param onAdd Opens the add dialog.
 * @param onEdit Opens the edit dialog for one reference.
 * @param onRemove Asks to remove one reference.
 */
export function RequestReferencesCard({
  references, canEdit, onAdd, onEdit, onRemove,
}: {
  references: ExternalRef[];
  canEdit: boolean;
  onAdd: () => void;
  onEdit: (reference: ExternalRef) => void;
  onRemove: (reference: ExternalRef) => void;
}) {
  return (
    <DetailCard
      heading="External references"
      action={canEdit ? <button className="btn btn-sm" onClick={onAdd}>Add reference</button> : undefined}
    >
      {references.length === 0 ? (
        <p className="text-muted">
          {canEdit ? "No outside tickets yet. Add the Jira or ServiceNow item this came from, or is delivered in." : "No outside tickets are recorded for this request."}
        </p>
      ) : (
        <table className="table" aria-label="External references">
          <thead><tr><th>System</th><th>Item</th><th>Role</th>{canEdit && <th><span className="sr-only">Actions</span></th>}</tr></thead>
          <tbody>
            {references.map((ref) => {
              const text = ref.key || ref.url || "";
              return (
                <tr key={ref.id}>
                  <td>{ref.system_name}</td>
                  <td>
                    {ref.url && isWebUrl(ref.url)
                      ? <a href={ref.url} target="_blank" rel="noopener noreferrer">{text}</a>
                      : text}
                  </td>
                  <td><Badge tone={ref.role === "origin" ? "info" : "accent"}>{EXTERNAL_REF_ROLE_LABEL[ref.role]}</Badge></td>
                  {canEdit && (
                    <td>
                      <span className="row" style={{ gap: "var(--space-1)" }}>
                        <button className="btn btn-sm btn-icon" aria-label={`Edit reference ${text}`} title="Edit" onClick={() => onEdit(ref)}>
                          <Pencil size={14} aria-hidden="true" />
                        </button>
                        <button className="btn btn-sm btn-icon" aria-label={`Remove reference ${text}`} title="Remove" onClick={() => onRemove(ref)}>
                          <Trash2 size={14} aria-hidden="true" />
                        </button>
                      </span>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </DetailCard>
  );
}
