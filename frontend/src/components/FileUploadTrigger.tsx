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
 * JSX per call site. See "File upload triggers:
 * three different visual treatments".
 *
 * Deliberately not used for the three bundle-import (.zip) forms
 * (`ServerOrganisationsPage`, `OrgAdminPage`'s import/merge,
 * `ProjectListPage`) — those keep the file picker as a visible,
 * `.input`-classed form field alongside other visible text fields ahead of
 * a separate submit step, which is a genuinely different shape (a form
 * field to fill in, not a one-click trigger that acts immediately) than
 * every other call site converted here. See docs/decisions.md.
 *
 * While the server administrator has disabled file uploads (`useFileUploadsEnabled`) every trigger renders as
 * an unavailable button that explains why in a tooltip, and the input is disabled: one place covers every
 * call site, and the control stays visible so it does not read as a defect.
 */
import type { ChangeEvent, ReactNode } from "react";
import { forwardRef } from "react";

import { useFileUploadsEnabled } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { Tooltip } from "./Tooltip";

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
  const uploadsEnabled = useFileUploadsEnabled();
  const strings = useStrings();
  const unavailable = !uploadsEnabled;

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
      disabled={disabled || unavailable}
      style={{ display: "none" }}
      onChange={handleChange}
    />
  );

  if (!showTrigger) return input;

  if (unavailable) {
    return (
      <Tooltip label={strings.fileUploads.unavailable} pinnable wrap>
        <span
          className={`btn${className ? ` ${className}` : ""}`} role="button" tabIndex={0} aria-disabled="true"
          aria-label={ariaLabel}
        >
          {children}
          {input}
        </span>
      </Tooltip>
    );
  }

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
