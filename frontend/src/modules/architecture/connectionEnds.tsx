/**
 * Module: modules/architecture/connectionEnds
 *
 * How a connection names its two ends in lists and on its page. An end the viewer can read shows its code and name; an
 * end they can no longer read (`locked`) shows only its code, so a connection to an element that stopped being shared is
 * still understood without revealing the element.
 */
import { RecordCode } from "../../components/RecordCode";
import type { ArchitectureConnection } from "./types";

/** One end of a connection: its code and, unless locked, its name and port. */
export function ConnectionEnd({
  connection, end,
}: { connection: ArchitectureConnection; end: "source" | "target" }) {
  const code = end === "source" ? connection.source_element_code : connection.target_element_code;
  const name = end === "source" ? connection.source_element_name : connection.target_element_name;
  const port = end === "source" ? connection.source_port_name : connection.target_port_name;
  const locked = end === "source" ? connection.source_locked : connection.target_locked;
  return (
    <span>
      <RecordCode code={code} />{!locked && <> {name}{port ? ` (${port})` : ""}</>}
      {locked && <span className="text-muted"> (not visible)</span>}
    </span>
  );
}
