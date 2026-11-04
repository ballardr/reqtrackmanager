/**
 * Module: components/ReportSnippetMenu
 *
 * The designer toolbar's one snippet control: an icon button that opens a menu with Insert snippet and Save as snippet.
 *
 * Responsibilities: name the button and the menu, and grey Save as snippet out with its reason when nothing can be saved.
 * It holds no state of its own; the Blocks and Text views each pass the two actions, so both toolbars read the same.
 */
import { Puzzle } from "lucide-react";

import { useStrings } from "../context/TerminologyContext";
import { ActionMenu, type ActionMenuItem } from "./ActionMenu";

/**
 * @param onInsert Opens the snippet picker; omit where snippets cannot be inserted (no Insert snippet item).
 * @param onSave Starts saving the selection as a snippet; omit where it cannot be saved (no Save as snippet item).
 * @param saveDisabledReason When set, Save as snippet is greyed out and this is its tooltip (nothing is selected yet).
 */
export function ReportSnippetMenu({
  onInsert, onSave, saveDisabledReason,
}: {
  onInsert?: () => void;
  onSave?: () => void;
  saveDisabledReason?: string;
}) {
  const text = useStrings().reportSnippets;
  const items: ActionMenuItem[] = [];
  if (onInsert) items.push({ key: "insert", label: text.insertButton, title: text.insertButtonLabel, onSelect: onInsert });
  if (onSave) {
    items.push({ key: "save", label: text.saveButton, title: saveDisabledReason, disabled: saveDisabledReason !== undefined, onSelect: onSave });
  }
  if (items.length === 0) return null;
  return <ActionMenu triggerLabel={text.menuButton} items={items} icon={<Puzzle aria-hidden="true" />} />;
}
