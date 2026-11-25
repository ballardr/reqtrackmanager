/**
 * Module: components/FileUploadTrigger
 *
 * Shared "styled button, hidden input" file picker trigger used by every file input (attachments, avatar,
 * organisation and platform logo and login background, shared resources), so each does not re-derive the markup.
 *
 * Not used for the bundle-import (.zip) forms (`ServerOrganisationsPage`, `OrgAdminPage`, `ProjectListPage`): they
 * keep a visible `.input` file field among other text fields ahead of a submit step, a form field rather than a
 * one-click trigger (docs/decisions.md).
 *
 * While file uploads are disabled for the deployment or the organisation in view (`Branding.fileUploadsDisabledBy`)
 * every trigger renders as an unavailable button explaining which in a tooltip, with the input disabled; it stays
 * visible so it does not read as a defect.
 */
import type { ChangeEvent, ReactNode } from "react";
import { forwardRef } from "react";

import { useBranding } from "../context/BrandingContext";
import { useStrings } from "../context/TerminologyContext";
import { Tooltip } from "./Tooltip";

export const FileUploadTrigger = forwardRef<
  HTMLInputElement,
  {
    onSelect: (file: File) => void;
    /** Several files at once: the input accepts more than one and this is called with all of them (in place of `onSelect`). */
    onSelectMany?: (files: File[]) => void;
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
  { onSelect, onSelectMany, children, id, accept, disabled, title, "aria-label": ariaLabel, className, showTrigger = true },
  ref
) {
  const { fileUploadsDisabledBy: disabledBy } = useBranding();
  const strings = useStrings();
  const unavailable = disabledBy !== null;

  function handleChange(e: ChangeEvent<HTMLInputElement>) {
    if (onSelectMany) {
      const files = Array.from(e.target.files ?? []);
      if (files.length > 0) onSelectMany(files);
    } else {
      const file = e.target.files?.[0];
      if (file) onSelect(file);
    }
    e.target.value = "";
  }

  const input = (
    <input
      ref={ref}
      id={id}
      type="file"
      multiple={onSelectMany !== undefined}
      accept={accept}
      disabled={disabled || unavailable}
      style={{ display: "none" }}
      onChange={handleChange}
    />
  );

  if (!showTrigger) return input;

  if (unavailable) {
    return (
      <Tooltip label={disabledBy === "organization" ? strings.fileUploads.unavailableOrganization : strings.fileUploads.unavailable} pinnable wrap>
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
