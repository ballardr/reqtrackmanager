/**
 * Module: modules/architecture/SelectionActions
 *
 * The row of actions on a diagram editor's Selection card, shared by the block diagram and the state machine editor so a
 * new action, and each action's icon and wording, reach both.
 * - A frequent, unmistakable action is a small icon button (`IconAction`: accessible name and tooltip are the same words).
 * - A rare or hard-to-picture action (`menu: true`) joins one overflow menu (a kebab `ActionMenu`) with a labelled list,
 *   never a second row of text buttons.
 * - A destructive action carries the danger outline; its confirmation tier is the caller's (the page asks before deleting).
 *
 * Design decisions:
 * - The icon of each common action is fixed in `selectionAction`, so Edit is a pencil in every card.
 * - The row renders nothing when there is nothing to offer, so a read-only card has no empty strip.
 */
import { ActionMenu, type ActionMenuItem } from "../../components/ActionMenu";
import { IconAction } from "../../components/IconAction";
import type { SelectionAction } from "./selectionAction";

/**
 * @param actions The actions to offer, in display order; falsy entries are skipped so a caller can write
 *   `editable && selectionAction.edit(...)`.
 * @param label The group's accessible name.
 */
export function SelectionActions({ actions, label = "Actions" }: { actions: (SelectionAction | false | null | undefined)[]; label?: string }) {
  const offered = actions.filter((a): a is SelectionAction => Boolean(a));
  const buttons = offered.filter((a) => !a.menu || a.to !== undefined);
  const menu = offered.filter((a) => a.menu && a.to === undefined);
  if (offered.length === 0) return null;
  const items: ActionMenuItem[] = menu.map((a) => ({
    label: a.label, icon: a.icon, danger: a.danger, onSelect: () => a.onSelect?.(),
  }));
  return (
    <div className="row" role="group" aria-label={label} style={{ gap: "var(--space-2)", flexWrap: "wrap" }}>
      {buttons.map((a) => (
        <IconAction key={a.label} label={a.label} to={a.to} danger={a.danger} help={a.help} onClick={a.onSelect}>{a.icon}</IconAction>
      ))}
      {items.length > 0 && <ActionMenu triggerLabel="More actions" size="sm" items={items} />}
    </div>
  );
}
