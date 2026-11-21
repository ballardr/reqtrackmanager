/**
 * Module: components/ServiceBadge
 *
 * The one "Service" pill shown beside a service user's name wherever a user or principal is listed (member lists,
 * owner and assignee fields, token lists), so an integration identity is never mistaken for a person.
 */
import { useStrings } from "../context/TerminologyContext";
import { Badge } from "./Badge";
import { Tooltip } from "./Tooltip";

/** The "Service" badge; its tooltip says what a service user is. */
export function ServiceBadge() {
  const strings = useStrings().serviceUsers;
  return (
    <Tooltip label={strings.badgeHint} wrap>
      <Badge tone="info">{strings.badge}</Badge>
    </Tooltip>
  );
}
