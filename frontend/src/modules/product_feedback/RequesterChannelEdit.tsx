/**
 * Module: modules/product_feedback/RequesterChannelEdit
 *
 * The pencil beside a requester's channel in the Demand panel: opens a small popover with the project's channel list
 * to record (or clear) how that requester asked. One or two fields, so a popover (`AddPopoverButton`), not a dialog.
 */
import { Pencil } from "lucide-react";
import { useState } from "react";

import { AddPopoverButton } from "../../components/AddPopoverButton";
import { LabeledSelect } from "../../components/LabeledSelect";
import { PRODUCT_FEEDBACK_HELP } from "./help";
import type { ChannelRef } from "./types";
import type { ListChoice } from "./useFeedbackLists";

/**
 * @param who The requester's name, for the accessible names.
 * @param current The channel now recorded, or null.
 * @param channels The channels the project offers.
 * @param onSave Records the chosen channel id (null clears it); rejects with the server's message.
 */
export function RequesterChannelEdit({
  who, current, channels, onSave,
}: { who: string; current: ChannelRef | null; channels: ListChoice[]; onSave: (channelId: string | null) => Promise<void> }) {
  return (
    <AddPopoverButton label={`Set channel for ${who}`} icon={Pencil}>
      {(close) => <ChannelForm who={who} current={current} channels={channels} onSave={async (id) => { await onSave(id); close(); }} />}
    </AddPopoverButton>
  );
}

function ChannelForm({
  who, current, channels, onSave,
}: { who: string; current: ChannelRef | null; channels: ListChoice[]; onSave: (channelId: string | null) => Promise<void> }) {
  const [value, setValue] = useState(current?.id ?? "");
  return (
    <div className="stack">
      <LabeledSelect
        help={PRODUCT_FEEDBACK_HELP.requesterChannel} label="Channel" ariaLabel={`Channel for ${who}`}
        value={value} onChange={setValue} options={channels} placeholder="Not recorded"
      />
      <div><button className="btn btn-primary btn-sm" onClick={() => void onSave(value || null)}>Save</button></div>
    </div>
  );
}
