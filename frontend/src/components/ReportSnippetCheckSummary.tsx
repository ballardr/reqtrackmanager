/**
 * Module: components/ReportSnippetCheckSummary
 *
 * What the server's check of a snippet says, shared by the save dialog and the snippet editor so both word it the same way: a
 * spinner while it runs, the check's own failure, how many blocks would be stored and what they carry, or the reasons the
 * blocks cannot be stored as they are.
 */
import type { SnippetCheck } from "../api/reportSnippets";
import { useStrings } from "../context/TerminologyContext";
import { Spinner } from "./Spinner";

/**
 * @param check The latest check for what is on screen, or `null` while one is running.
 * @param error Why the check itself could not run (shown instead of a result).
 */
export function ReportSnippetCheckSummary({ check, error }: { check: SnippetCheck | null; error: string | null }) {
  const text = useStrings().reportSnippetSave;
  return (
    <>
      {check === null && error === null && <Spinner />}
      {error && <p role="alert" style={{ margin: 0, color: "var(--color-danger)" }}>{error}</p>}
      {check && check.ok && (
        <div className="stack" style={{ gap: "var(--space-1)" }} role="status">
          <span>{text.summary(check.blocks)}</span>
          {check.page_styles.length > 0 && <span className="text-muted">{text.carries(text.pageStyles, check.page_styles)}</span>}
          {check.variables.length > 0 && <span className="text-muted">{text.carries(text.variables, check.variables)}</span>}
        </div>
      )}
      {check && !check.ok && (
        <div role="alert" className="stack" style={{ gap: "var(--space-1)", color: "var(--color-danger)" }}>
          <span>{text.refused}</span>
          <ul style={{ margin: 0 }}>{check.errors.map((e, index) => <li key={index}>{e.message}</li>)}</ul>
        </div>
      )}
    </>
  );
}
