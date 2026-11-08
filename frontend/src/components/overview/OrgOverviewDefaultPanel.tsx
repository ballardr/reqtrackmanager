/**
 * Module: components/overview/OrgOverviewDefaultPanel
 *
 * Organisation administration's "Default overview": the layout every project of the organisation shows unless it
 * (or a parent project) has its own. The shared overview editor, inline in the settings page, with a labelled block
 * for each widget in place of data (an organisation default has no project to read figures from).
 */
import { useState } from "react";

import { OverviewEditor } from "./OverviewEditor";

/**
 * @param organizationId The organisation whose default is edited.
 */
export function OrgOverviewDefaultPanel({ organizationId }: { organizationId: string }) {
  // Remounting the editor after a save, a restore or a cancel reloads what the server now holds.
  const [version, setVersion] = useState(0);
  const reload = () => setVersion((v) => v + 1);
  return <OverviewEditor key={version} target={{ kind: "organisation", organizationId }} onSaved={reload} onCancel={reload} />;
}
