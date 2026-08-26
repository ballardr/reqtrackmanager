/**
 * Module: components/FileUploadTrigger
 *
 * Shared "styled button, hidden input" file picker trigger. Extracted from
 * `CommentThread.tsx`'s own hand-rolled `<label className="btn">...<input
 * type="file" style={{ display: "none" }} /></label>` shape — the one place
 * in the app that already rendered file pickers as a real button rather
 * than the browser's bare native control — so every other file input
 * (attachments, avatar, org/platform logo & login background, shared
 * resources) can share one implementation instead of re-deriving the same
 * JSX per call site. See docs/ux-audit-2026-08.md "File upload triggers:
 * three different visual treatments".
 *
 * Deliberately not used for the three bundle-import (.zip) forms
 * (`ServerOrganisationsPage`, `OrgAdminPage`'s import/merge,
 * `ProjectListPage`) — those keep the file picker as a visible,
 * `.input`-classed form field alongside other visible text fields ahead of
 * a separate submit step, which is a genuinely different shape (a form
 * field to fill in, not a one-click trigger that acts immediately) than
 * every other call site converted here. See docs/decisions.md.
 */
import type { ChangeEvent, ReactNode } from "react";
import { forwardRef } from "react";

export const FileUploadTrigger = forwardRef<
  HTMLInputElement,
  {
    onSelect: (file: File) => void;
    children: ReactNode;
    id?: string;
    accept?: string;
    disabled?: boolean;
    title?: string;
    "aria-label"?: string;
    className?: string;
    /** When false, renders only the (still-mounted, still hidden) input —
     * no visible trigger — so a caller can open the picker itself via a
     * forwarded ref's `.click()`, e.g. from a split-button's own trigger. */
    showTrigger?: boolean;
  }
>(function FileUploadTrigger(
  { onSelect, children, id, accept, disabled, title, "aria-label": ariaLabel, className, showTrigger = true },
  ref
) {
  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) onSelect(file);
    e.target.value = "";
  }

  const input = (
    <input
      ref={ref}
      id={id}
      type="file"
      accept={accept}
      disabled={disabled}
      style={{ display: "none" }}
      onChange={handleChange}
    />
  );

  if (!showTrigger) return input;

  return (
    <label
      htmlFor={id}
      className={`btn${className ? ` ${className}` : ""}`}
      style={{ cursor: disabled ? "wait" : "pointer" }}
      title={title}
      aria-label={ariaLabel}
    >
      {children}
      {input}
    </label>
  );
});
