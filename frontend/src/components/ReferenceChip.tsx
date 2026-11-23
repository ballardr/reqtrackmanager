/**
 * Module: components/ReferenceChip
 *
 * One external reference as a chip: `System: key` (the key opens the item in a new tab when it has a web link), the role
 * as a badge, a leading link icon, and the note (or "External reference") as a tooltip. The edit and remove buttons show
 * only when their handlers are given. Used by the record header's chip row (`RecordTags`).
 */
import { Link2, Pencil, Trash2 } from "lucide-react";

import {
  EXTERNAL_REFERENCE_ROLE_LABEL, isWebUrl, referenceLabel, type ExternalReference,
} from "../api/externalReferences";
import { useStrings } from "../context/TerminologyContext";
import { Badge } from "./Badge";
import { Tooltip } from "./Tooltip";

/**
 * @param reference The reference.
 * @param onEdit Opens the editor.
 * @param onRemove Asks to remove it.
 */
export function ReferenceChip({
  reference, onEdit, onRemove,
}: { reference: ExternalReference; onEdit?: () => void; onRemove?: () => void }) {
  const strings = useStrings();
  const text = strings.references;
  const key = reference.key || reference.url || "";
  const href = isWebUrl(reference.link) ? reference.link : null;
  const label = referenceLabel(reference);
  return (
    <Tooltip label={reference.note ? `${text.kind}: ${reference.note}` : text.kind}>
      <span className="chip">
        <Link2 size={12} aria-hidden="true" style={{ flex: "none" }} />
        <span className="chip__label">
          {reference.system_name}:{" "}
          {href ? <a href={href} target="_blank" rel="noopener noreferrer" aria-label={text.openLink(label)}>{key}</a> : key}
        </span>
        {reference.role && <Badge>{EXTERNAL_REFERENCE_ROLE_LABEL[reference.role]}</Badge>}
        {onEdit && (
          <button type="button" className="chip__remove" aria-label={text.editLabel(label)} onClick={onEdit}>
            <Pencil size={12} />
          </button>
        )}
        {onRemove && (
          <button type="button" className="chip__remove" aria-label={text.removeLabel(label)} onClick={onRemove}>
            <Trash2 size={12} />
          </button>
        )}
      </span>
    </Tooltip>
  );
}
