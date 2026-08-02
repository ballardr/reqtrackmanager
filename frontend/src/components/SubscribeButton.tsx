import { Bell, BellOff } from "lucide-react";

import { t } from "../i18n/strings";

const strings = t();

/** Toggle button for per-entity subscriptions (mockup: "Subscribed" panel on requirement/CR detail views). */
export function SubscribeButton({
  subscribed,
  onToggle,
}: {
  subscribed: boolean;
  onToggle: () => void;
}) {
  return (
    <button className={`btn ${subscribed ? "btn-primary" : ""}`} onClick={onToggle}>
      {subscribed ? <Bell size={16} /> : <BellOff size={16} />}
      {subscribed ? strings.requirements.subscribed : strings.requirements.subscribe}
    </button>
  );
}
