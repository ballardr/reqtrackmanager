/**
 * Module: components/AddUserMenu
 *
 * The one "Add user ▾" button both user lists use (Server Management → Users and Org Admin → Users):
 * a menu of the two ways to add a person, each opening its own dialog.
 *
 * - Invite user: emails a sign-up link, so the person chooses their own name and password.
 * - New user: an account the administrator creates now, with a password they type.
 *
 * The pages own the dialogs and what each one posts; this component is only the entry point, so the two
 * pages cannot drift in wording or order (docs/ux-style-guide.md, "Pattern: action menu").
 */
import { Plus, Send } from "lucide-react";

import { t } from "../i18n/strings";
import { MenuButton } from "./MenuButton";

const strings = t();

/**
 * @param onInvite Called when "Invite user" is chosen.
 * @param onNewUser Called when "New user" is chosen.
 * @param disabled Disables the button.
 */
export function AddUserMenu({
  onInvite, onNewUser, disabled,
}: {
  onInvite: () => void;
  onNewUser: () => void;
  disabled?: boolean;
}) {
  return (
    <MenuButton
      primary
      disabled={disabled}
      label={<><Plus aria-hidden="true" /> {strings.system.addUser}</>}
      menuLabel={strings.system.addUser}
      items={[
        { key: "invite", label: strings.orgAdmin.inviteUser, icon: <Send aria-hidden="true" />, onSelect: onInvite },
        { key: "new", label: strings.orgAdmin.newUser, icon: <Plus aria-hidden="true" />, onSelect: onNewUser },
      ]}
    />
  );
}
