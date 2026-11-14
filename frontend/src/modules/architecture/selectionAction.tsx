/**
 * Module: modules/architecture/selectionAction
 *
 * The description of one Selection card action and the common actions with their icons, shared by the block diagram's and
 * the state machine editor's cards (rendered by `SelectionActions`), so Edit is a pencil in every card and a new action
 * reaches both.
 */
import {
  CircleMinus, ExternalLink, Layers, MessageSquarePlus, Pencil, Trash2, X,
} from "lucide-react";
import type { ReactNode } from "react";

/** One action of a Selection card. */
export interface SelectionAction {
  /** The action's name: the button's accessible name and tooltip, or the menu item's label. */
  label: string;
  /** The icon shown on the button (and before the menu item's label). */
  icon: ReactNode;
  /** Called when the action is chosen (not used when `to` is set). */
  onSelect?: () => void;
  /** A route to open: the action is a link. */
  to?: string;
  /** Draws the destructive outline. */
  danger?: boolean;
  /** What the action does when its name does not say; shown under the name in the tooltip. */
  help?: string;
  /** Puts the action in the overflow menu instead of on the row (a link cannot be a menu item, so `to` ignores it). */
  menu?: boolean;
}

/** The common actions with their icons; each takes the card's own wording. */
export const selectionAction = {
  /** Opens a record's page. */
  open: (label: string, to: string): SelectionAction => ({ label, to, icon: <ExternalLink /> }),
  /** Opens an element's inside as a diagram. */
  inside: (label: string, onSelect: () => void): SelectionAction => ({ label, onSelect, icon: <Layers /> }),
  /** Edits the selected record. */
  edit: (label: string, onSelect: () => void): SelectionAction => ({ label, onSelect, icon: <Pencil /> }),
  /** Starts a comment on the selection. */
  comment: (label: string, onSelect: () => void): SelectionAction => ({ label, onSelect, icon: <MessageSquarePlus /> }),
  /** Takes the selection off the diagram without changing the model. */
  remove: (label: string, onSelect: () => void): SelectionAction => ({ label, onSelect, icon: <CircleMinus /> }),
  /** Deletes the selection (the caller confirms). */
  delete: (label: string, onSelect: () => void): SelectionAction => ({ label, onSelect, icon: <Trash2 />, danger: true }),
  /** Removes a note. */
  clear: (label: string, onSelect: () => void): SelectionAction => ({ label, onSelect, icon: <X />, danger: true }),
};
