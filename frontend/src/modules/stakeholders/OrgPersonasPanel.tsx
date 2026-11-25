/**
 * Module: modules/stakeholders/OrgPersonasPanel
 *
 * An organisation's own Personas (one live, shared record every project can see and score against), rendered as an
 * `OrgResourcesPage` `ResourceMenu` group (`module.ts`'s `orgResourceSections`).
 *
 * Placement follows the Guiding Principle and Strategy organisation panels: an organisation persona is content its
 * owners work with and projects reuse, not configuration; the Persona types are the configuration and live on
 * `orgAdminSections`. The list, filter and create UI is the shared `PersonaListView`.
 */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Spinner } from "../../components/Spinner";
import { toErrorMessage, useToast } from "../../context/ToastContext";
import { orgPersonaApi, orgPersonaTypeApi } from "./api";
import { PersonaListView } from "./PersonaListView";
import type { Persona, PersonaTypeDefinition } from "./types";

export function OrgPersonasPanel({ orgId }: { orgId: string }) {
  const navigate = useNavigate();
  const { showToast } = useToast();
  const [personas, setPersonas] = useState<Persona[] | null>(null);
  const [types, setTypes] = useState<PersonaTypeDefinition[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [includeArchived, setIncludeArchived] = useState(false);

  const [refreshKey, setRefreshKey] = useState(0);
  const reload = () => setRefreshKey((k) => k + 1);

  useEffect(() => {
    let active = true;
    Promise.all([orgPersonaApi.list(orgId, { include_archived: includeArchived }), orgPersonaTypeApi.list(orgId)])
      .then(([list, typeList]) => {
        if (!active) return;
        setPersonas(list);
        setTypes(typeList);
        setLoadError(null);
      })
      .catch((err) => {
        if (active) setLoadError(toErrorMessage(err, "The Stakeholders & Personas module is not enabled for this organisation, or you do not have access to it."));
      });
    return () => {
      active = false;
    };
  }, [orgId, includeArchived, refreshKey]);

  if (loadError) return <p className="text-muted">{loadError}</p>;
  if (personas === null) return <Spinner />;

  return (
    <PersonaListView
      personas={personas}
      ariaLabel="Organisation Personas"
      sectionKey="stakeholders.orgPersonas.list"
      scopeLabel="organisation"
      emptyText="No organisation-scoped Personas recorded yet."
      showScope={false}
      showEffectiveWeight={false}
      typeOptions={types.filter((t) => t.is_active).map((t) => ({ value: t.id, label: t.name }))}
      includeArchived={includeArchived}
      onIncludeArchivedChange={setIncludeArchived}
      exportRecords={{ organizationId: orgId, onImported: reload }}
      onOpen={(p) => navigate(`/orgs/${orgId}/modules/stakeholders/personas/${p.id}`)}
      onCreate={async (values) => {
        await orgPersonaApi.create(orgId, values);
        showToast("Persona created.");
        reload();
      }}
    />
  );
}
