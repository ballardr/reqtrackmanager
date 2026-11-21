/**
 * Module: components/ServiceUserFlags
 *
 * The access-review flags of a service user as pills, each with a tooltip saying what it means and what to do. One
 * rendering for the list and the detail dialog.
 */
import type { ServiceUserFlag } from "../api/serviceUsers";
import { useStrings } from "../context/TerminologyContext";
import { Badge } from "./Badge";
import { Tooltip } from "./Tooltip";

/**
 * @param flags The flags the server reported; nothing is drawn for none.
 */
export function ServiceUserFlags({ flags }: { flags: ServiceUserFlag[] }) {
  const text = useStrings().serviceUsers;
  const label: Record<ServiceUserFlag, [string, string]> = {
    no_responsible: [text.flagNoResponsible, text.flagNoResponsibleHint],
    administrator: [text.flagAdministrator, text.flagAdministratorHint],
  };
  return (
    <span className="row" style={{ gap: "var(--space-1)", flexWrap: "wrap" }}>
      {flags.map((flag) => (
        <Tooltip key={flag} label={label[flag][1]} wrap>
          <Badge tone="warning">{label[flag][0]}</Badge>
        </Tooltip>
      ))}
    </span>
  );
}
