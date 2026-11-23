/** Triggers a browser save-as download for an in-memory Blob; the one place the
 * anchor-click download is done for every export feature. */
export function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  // An anchor not attached to the document before `.click()` can lose its
  // `download` filename and extension in some browsers.
  // rather than only working in browsers lenient enough not to need this.
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
