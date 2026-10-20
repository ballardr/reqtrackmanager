/**
 * Module: components/SearchHitSummary
 *
 * One global-search result as the header dropdown and the search page both show it, so the two
 * cannot drift: the record's code, its title (with the matched words highlighted), a type pill, a
 * status pill, where it lives, and, on the page, the snippet of the field the match was found in.
 *
 * The code is qualified by its owning project (or organisation) because a search spans projects
 * (`hitCode`). An organisation-owned record names the organisation rather than a project.
 */
import { hitCode, highlightParts, matchRanges, type SearchHit } from "../api/search";
import { useStrings } from "../context/TerminologyContext";
import { Badge } from "./Badge";

/** Text with the given `[start, end)` ranges wrapped in `<mark>`. */
export function Highlighted({ text, ranges }: { text: string; ranges: [number, number][] }) {
  return (
    <>
      {highlightParts(text, ranges).map((part, i) =>
        part.mark ? (
          <mark key={i} className="search-mark">
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </>
  );
}

/**
 * @param hit The result.
 * @param terms The lower-case words searched for, to highlight in the code and title.
 * @param showSnippet Show the matching field's text under the title (the page; not the dropdown).
 */
export function SearchHitSummary({ hit, terms, showSnippet = false }: { hit: SearchHit; terms: string[]; showSnippet?: boolean }) {
  const strings = useStrings();
  const code = hitCode(hit);
  const where = hit.type === "project" ? null : hit.project_name ? strings.search.inProject(hit.project_name) : strings.search.inOrganisation;
  return (
    <span className="stack" style={{ gap: "0.15rem", minWidth: 0 }}>
      <span style={{ overflowWrap: "anywhere" }}>
        {code && (
          <span className="text-muted" style={{ fontSize: "0.8rem" }}>
            <Highlighted text={code} ranges={matchRanges(code, terms)} />{" "}
          </span>
        )}
        <Highlighted text={hit.title} ranges={matchRanges(hit.title, terms)} />
      </span>
      <span className="row" style={{ gap: "0.4rem", fontSize: "0.8rem" }}>
        <Badge>{hit.type_label}</Badge>
        {hit.status_label && <Badge tone="muted">{hit.status_label}</Badge>}
        {hit.is_archived && <Badge tone="warning">{strings.search.archivedBadge}</Badge>}
        {where && <span className="text-muted">{where}</span>}
      </span>
      {showSnippet && hit.snippet && (
        <span className="text-muted" style={{ fontSize: "0.85rem", overflowWrap: "anywhere" }}>
          <strong style={{ fontWeight: 600 }}>{hit.snippet.field_label}:</strong>{" "}
          <Highlighted text={hit.snippet.text} ranges={hit.snippet.ranges} />
        </span>
      )}
    </span>
  );
}
