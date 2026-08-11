/** Triggers a browser save-as download for an in-memory Blob. Shared by
 * every export feature (reports, CSV import template, requirement/project/
 * org bundle exports) so the anchor-click download dance lives in one
 * place. */
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  // Some browsers ignore `download` (falling back to a generic,
  // extension-less blob id as the saved filename) for an anchor that was
  // never actually attached to the document before `.click()` — appending
  // it is what makes the filename (and its extension) reliably apply
  // rather than only working in browsers lenient enough not to need this.
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
