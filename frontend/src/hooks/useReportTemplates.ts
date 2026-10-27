/**
 * Module: hooks/useReportTemplates
 *
 * Loads an organisation's report templates (the branding a PDF or Word report can take), for the "Branding
 * template" choice beside a report's download. Shared by the report runner and the report pack runner.
 *
 * A failed load is an empty list: the choice is simply not offered, and a report still downloads unbranded.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { ReportTemplate } from "../api/types";

/**
 * @param organizationId The organisation whose templates to load; `undefined` loads nothing.
 * @returns The organisation's report templates (empty while loading or on a failed load).
 */
export function useReportTemplates(organizationId: string | undefined): ReportTemplate[] {
  const [loaded, setLoaded] = useState<{ organizationId: string; templates: ReportTemplate[] } | null>(null);
  useEffect(() => {
    if (!organizationId) return undefined;
    let cancelled = false;
    api
      .get<ReportTemplate[]>(`/api/v1/orgs/${organizationId}/report-templates`)
      .then((list) => !cancelled && setLoaded({ organizationId, templates: list }))
      .catch(() => !cancelled && setLoaded({ organizationId, templates: [] }));
    return () => {
      cancelled = true;
    };
  }, [organizationId]);
  return loaded !== null && loaded.organizationId === organizationId ? loaded.templates : [];
}
