/**
 * Module: modules/stakeholders/EngagementTimelinePanel
 *
 * A Stakeholder's or Persona's engagement history on its detail page, with the
 * "Log contact" quick add beside it. The history is the shared
 * `RepresentationPanel` (read-only: an engagement is edited on its own page),
 * newest first, each row "date · channel · title" linking to the engagement.
 * "Log contact" opens the compact `EngagementFormModal`, records an engagement
 * with this person (or Persona) already attached, toasts, and refreshes the
 * list, so a one-line email is a few seconds' work (Phase 0 addendum 2, item 20).
 * Renders nothing outside a project: engagements are project-scoped, so the
 * organisation route has no history to show.
 */
import { useState } from "react";

import { toErrorMessage, useToast } from "../../context/ToastContext";
import { projectEngagementApi } from "./api";
import { EngagementFormModal } from "./EngagementFormModal";
import { RepresentationPanel } from "./RepresentationPanel";
import type { EngagementFieldValues, StakeholderEngagement } from "./types";
import { ENGAGEMENT_CHANNEL_LABEL } from "./types";

/** Who the history belongs to: a Stakeholder takes part, a Persona is covered. */
export interface EngagementSubject {
  kind: "stakeholder" | "persona";
  id: string;
  name: string;
}

export function EngagementTimelinePanel({
  projectId,
  subject,
  load,
}: {
  /** `undefined` on the organisation route, where nothing is rendered. */
  projectId: string | undefined;
  subject: EngagementSubject;
  load: () => Promise<StakeholderEngagement[]>;
}) {
  const { showToast } = useToast();
  const [logging, setLogging] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  if (!projectId) return null;

  async function log(values: EngagementFieldValues) {
    if (!projectId) return;
    setError(null);
    try {
      await projectEngagementApi.create(projectId, {
        ...values,
        ...(subject.kind === "stakeholder" ? { stakeholder_ids: [subject.id] } : { persona_ids: [subject.id] }),
      });
      showToast("Contact logged.");
      setLogging(false);
      setReloadKey((k) => k + 1);
    } catch (err) {
      setError(toErrorMessage(err, "Could not log this contact."));
    }
  }

  return (
    <div className="stack" style={{ gap: "0.5rem" }}>
      <RepresentationPanel
        heading="Engagements"
        emptyText="No engagements logged yet."
        reloadKey={reloadKey}
        load={async () =>
          (await load()).map((e) => ({
            link_id: e.id, id: e.id, name: `${e.engagement_date} · ${ENGAGEMENT_CHANNEL_LABEL[e.channel]} · ${e.title}`, scope: "project" as const,
          }))
        }
        linkFor={(engagement) => `/projects/${projectId}/modules/stakeholders/engagements/${engagement.id}`}
      />
      <div className="row">
        <button className="btn" onClick={() => setLogging(true)}>Log contact</button>
      </div>
      {logging && (
        <EngagementFormModal
          compact
          heading={`Log contact with ${subject.name}`}
          defaults={{ title: `Contact with ${subject.name}`, channel: "email" }}
          error={error}
          onCancel={() => { setLogging(false); setError(null); }}
          onSave={log}
        />
      )}
    </div>
  );
}
