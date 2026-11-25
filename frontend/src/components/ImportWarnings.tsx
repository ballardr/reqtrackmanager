/**
 * Module: components/ImportWarnings
 *
 * The list of warnings an import returned (a succeeded import with skipped or adjusted content), so every import
 * result reads the same and takes its colour from the theme's warning token. Drawn as a titled card (or, inside a
 * card with its own heading, the bare coloured list); nothing when there are none.
 */

/**
 * @param warnings Warning messages from the import result; nothing is drawn when empty or null.
 * @param title Heading of the card; omit to draw only the coloured list (for use inside another card).
 */
export function ImportWarnings({ warnings, title }: { warnings: readonly string[] | null | undefined; title?: string }) {
  if (!warnings || warnings.length === 0) return null;
  const list = (
    <ul style={{ margin: 0, color: title === undefined ? "var(--color-warning)" : undefined }}>
      {warnings.map((w, i) => <li key={i}>{w}</li>)}
    </ul>
  );
  if (title === undefined) return list;
  return (
    <div className="card stack" role="status" style={{ borderColor: "var(--color-warning)" }}>
      <strong>{title}</strong>
      {list}
    </div>
  );
}
