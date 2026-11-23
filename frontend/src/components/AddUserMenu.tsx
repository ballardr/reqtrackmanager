/**
 * Module: components/AddUserMenu
 *
 * The one "Add user ▾" button both user lists use (Server Management → Users and Org Admin → Users):
 * a menu of the ways to add an account, each opening its own dialog.
 *
 * - Invite user: emails a sign-up link, so the person chooses their own name and password.
 * - New user: an account the administrator creates now, with a password they type.
 * - New service user (an organisation's list only): an integration's identity with no password and no sign-in, which
 *   acts through tokens an administrator issues. Absent where there is no single organisation to own it.
 *
 * The pages own the dialogs and what each one posts; this component is only the entry point, so the two
 * pages cannot drift in wording or order (docs/ux-style-guide.md, "Pattern: action menu").
 */
import { Bot, Plus, Send } from "lucide-react";

import { t } from "../i18n/strings";
import { MenuButton } from "./MenuButton";

const strings = t();

/**
 * @param onInvite Called when "Invite user" is chosen.
 * @param onNewUser Called when "New user" is chosen.
 * @param onNewServiceUser Called when "New service user" is chosen; omit to offer no such row.
 * @param disabled Disables the button.
 */
export function AddUserMenu({
  onInvite, onNewUser, onNewServiceUser, disabled,
}: {
  onInvite: () => void;
  onNewUser: () => void;
  onNewServiceUser?: () => void;
  disabled?: boolean;
}) {
  return (
    <MenuButton
      primary
      disabled={disabled}
      label={<><Plus aria-hidden="true" /> {strings.system.addUser}</>}
      menuLabel={strings.system.addUser}
      help={onNewServiceUser ? strings.system.addUserMenuHelpWithService : strings.system.addUserMenuHelp}
      items={[
        { key: "invite", label: strings.orgAdmin.inviteUser, icon: <Send aria-hidden="true" />, onSelect: onInvite },
        { key: "new", label: strings.orgAdmin.newUser, icon: <Plus aria-hidden="true" />, onSelect: onNewUser },
        ...(onNewServiceUser
          ? [{ key: "service", label: strings.serviceUsers.create, icon: <Bot aria-hidden="true" />, onSelect: onNewServiceUser }]
          : []),
      ]}
    />
  );
}
