/**
 * Module: components/ResultActions
 *
 * The header actions of a dialog that has finished its work and now shows what happened (an import's or
 * copy's result): one primary **OK** that closes it, plus any extra control (a download of the failures).
 * Mounting it also marks the dialog settled, so closing it by OK, Escape or the close mark never asks to
 * discard the earlier steps' choices, which were applied (docs/ux-style-guide.md, "Pattern: result dialog").
 */
import { useEffect, type ReactNode } from "react";

import { t } from "../i18n/strings";
import { FormActions } from "./FormActions";
import { useDialogSlots } from "./dialogSlots";

const strings = t();

/**
 * @param onOk Closes the dialog.
 * @param children Extra controls placed before OK (e.g. "Download error file").
 */
export function ResultActions({ onOk, children }: { onOk: () => void; children?: ReactNode }) {
  const registerSettled = useDialogSlots()?.registerSettled;
  useEffect(() => registerSettled?.(), [registerSettled]);
  return <FormActions onCancel={onOk} onSave={onOk} saveLabel={strings.common.ok}>{children}</FormActions>;
}
