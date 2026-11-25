/**
 * Module: components/AddUserMenu
 *
 * The one "Add user" menu button both user lists use (Server Management and Org Admin Users); each row opens its
 * own dialog, owned by the page, which also owns what each posts.
 *
 * - Invite user: emails a sign-up link, so the person chooses their own name and password.
 * - New user: an account the administrator creates immediately, with a typed password.
 * - New service user (organisation list only): an integration identity with no password or sign-in, acting through
 *   administrator-issued tokens. Absent where no single organisation owns it.
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
