/**
 * Module: components/ReferencesCell
 *
 * A record's external references as one table cell: `System: key` for each, the key opening the item in a new tab when
 * the reference has a web link. Used by `DirectoryTable`'s External references column and by the hand-written tables
 * that read the page's references with `usePageReferences`.
 */
import { isWebUrl, referenceLabel, type ExternalReference } from "../api/externalReferences";
import { useStrings } from "../context/TerminologyContext";

/**
 * @param references The record's references (nothing is drawn for none).
 */
export function ReferencesCell({ references }: { references: ExternalReference[] | undefined }) {
  const strings = useStrings().references;
  if (!references || references.length === 0) return null;
  return (
    <span className="stack" style={{ gap: 0 }}>
      {references.map((reference) => {
        const text = reference.key || reference.url || "";
        return (
          <span key={reference.id}>
            {reference.system_name}:{" "}
            {isWebUrl(reference.link) ? (
              <a href={reference.link} target="_blank" rel="noopener noreferrer" aria-label={strings.openLink(referenceLabel(reference))}>{text}</a>
            ) : text}
          </span>
        );
      })}
    </span>
  );
}
