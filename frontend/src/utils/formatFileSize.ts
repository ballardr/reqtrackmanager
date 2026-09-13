/** Human-readable file size (e.g. "12.4 KB"). Extracted (compliance-module-
 * plan.md Phase 19) from `pages/ProjectFilesPage.tsx`'s own previously-local
 * helper, which named a second call site as the trigger for promoting it —
 * `pages/OrgOverviewPage.tsx`'s stats header (`total_file_size_bytes`) is
 * that second call site. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`;
}
