/**
 * Module: components/useConfirmedAction
 *
 * Pairs one object-action menu item with the confirmation dialog it opens, so a
 * detail page lists its Archive / Delete permanently actions in `RecordHeader`'s
 * menu without hand-rolling `useState` plus a `ConfirmDialog` per action
 * (style guide "Pattern: record header and object actions").
 *
 * - Tier 1 (plain Cancel/confirm) by default; passing `requireTypedText` makes it
 *   Tier 2 (type the exact name), exactly as `ConfirmDialog` already does.
 * - `useArchiveAction` is the Archive/Unarchive (or Restore) case every record has.
 * - A hidden action (no permission) yields `item: null`; it is never rendered disabled.
 *
 * External dependencies: `ConfirmDialog`, `ActionMenu`'s item type.
 */
import { useState, type ReactNode } from "react";

import type { ActionMenuItem } from "./ActionMenu";
import { ConfirmDialog } from "./ConfirmDialog";

export interface ConfirmedActionConfig {
  /** Menu item label, also the default confirm button label. */
  label: string;
  icon?: ReactNode;
  /** Danger outline on the menu item (Archive, Delete permanently). */
  danger?: boolean;
  /** Omit the action entirely (the user may not perform it). */
  hidden?: boolean;
  /** Skip the dialog and run `onConfirm` straight away (a reversible action such as Restore). */
  immediate?: boolean;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  requireTypedText?: string;
  onConfirm: () => void | Promise<void>;
}

/**
 * @param config The action, or `null` when the page has none right now.
 * @returns `item` for `RecordHeader`'s `actions` (null when hidden) and `dialog`,
 *   which the page renders anywhere inside its tree.
 */
export function useConfirmedAction(config: ConfirmedActionConfig | null): {
  item: ActionMenuItem | null;
  dialog: ReactNode;
} {
  const [open, setOpen] = useState(false);
  if (!config || config.hidden) return { item: null, dialog: null };
  const { label, icon, danger, immediate, title, message, confirmLabel, requireTypedText, onConfirm } = config;
  return {
    item: {
      label,
      icon,
      danger,
      onSelect: () => (immediate ? void onConfirm() : setOpen(true)),
    },
    dialog: open ? (
      <ConfirmDialog
        title={title}
        message={message}
        confirmLabel={confirmLabel ?? label}
        requireTypedText={requireTypedText}
        onConfirm={async () => {
          setOpen(false);
          await onConfirm();
        }}
        onCancel={() => setOpen(false)}
      />
    ) : null,
  };
}

/**
 * The Archive / Unarchive object action every record has. Archiving asks for
 * confirmation (Tier 1); restoring is reversible and, by default, confirms too —
 * pass `restoreImmediately` for the requirement/action precedent that restores at once.
 *
 * @param noun Singular record name used in the dialog title ("Persona" -> "Archive this Persona?").
 * @param isArchived Current archive state.
 * @param archiveBody What archiving does.
 * @param onToggle Archives or unarchives; the page toasts its own outcome.
 * @param hidden True when the user may not archive this record.
 * @param labels Override the verbs ("Restore" instead of "Unarchive").
 */
export function useArchiveAction({
  noun,
  isArchived,
  archiveBody,
  onToggle,
  hidden,
  restoreImmediately,
  labels,
}: {
  noun: string;
  isArchived: boolean;
  archiveBody: ReactNode;
  onToggle: () => void | Promise<void>;
  hidden?: boolean;
  restoreImmediately?: boolean;
  labels?: { archive?: string; unarchive?: string };
}) {
  const archiveLabel = labels?.archive ?? "Archive";
  const unarchiveLabel = labels?.unarchive ?? "Unarchive";
  return useConfirmedAction({
    label: isArchived ? unarchiveLabel : archiveLabel,
    danger: !isArchived,
    hidden,
    immediate: isArchived && restoreImmediately,
    title: isArchived ? `${unarchiveLabel} this ${noun}?` : `${archiveLabel} this ${noun}?`,
    message: isArchived ? `This ${noun} will count as active again.` : archiveBody,
    onConfirm: onToggle,
  });
}
