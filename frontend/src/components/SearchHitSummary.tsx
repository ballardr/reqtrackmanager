/**
 * Module: components/SearchHitSummary
 *
 * One global-search result as the header dropdown and the search page both show it, so the two
 * cannot drift: the record's code, its title (with the matched words highlighted), a type pill, a
 * status pill, where it lives, and, on the page, the snippet of the field the match was found in.
 *
 * The code is qualified by its owning project (or organisation) because a search spans projects
 * (`hitCode`). An organisation-owned record names the organisation rather than a project.
 *
 * `density="compact"` (the dropdown) is one line per hit: muted code, title truncated with a tooltip
 * and the muted place right-aligned. The type is named by the dropdown's group heading, and the
 * status and snippet stay on the results page.
 */
import { hitCode, highlightParts, matchRanges, type SearchHit } from "../api/search";
import { useStrings } from "../context/TerminologyContext";
import { Badge } from "./Badge";
import { Tooltip } from "./Tooltip";

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
 * @param density `comfortable` (the page, default) or `compact` (one line, the dropdown).
 */
export function SearchHitSummary({
  hit, terms, showSnippet = false, density = "comfortable",
}: { hit: SearchHit; terms: string[]; showSnippet?: boolean; density?: "comfortable" | "compact" }) {
  const strings = useStrings();
  const code = hitCode(hit);
  const where = hit.type === "project" ? null : hit.project_name ? strings.search.inProject(hit.project_name) : strings.search.inOrganisation;
  if (density === "compact") {
    return (
      <span className="search-hit-compact">
        {code && (
          <span className="text-muted search-hit-compact__code">
            <Highlighted text={code} ranges={matchRanges(code, terms)} />
          </span>
        )}
        <Tooltip label={hit.title} className="search-hit-compact__title">
          <span className="search-hit-compact__text">
            <Highlighted text={hit.title} ranges={matchRanges(hit.title, terms)} />
          </span>
        </Tooltip>
        {where && <span className="text-muted search-hit-compact__where">{where}</span>}
      </span>
    );
  }
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
      <span className="row" style={{ gap: "var(--space-2)", fontSize: "0.8rem" }}>
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
