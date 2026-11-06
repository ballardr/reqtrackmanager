/**
 * Module: modules/product_feedback/FeedbackListPanels
 *
 * The admin screens of the module's two classified lists — the external systems a request's references can name and the
 * channels a requester can have asked through — as thin wrappers over the shared `OrgTypeVocabularyPanel` and
 * `ProjectTypeVocabularyPanel` (rename, reorder, disable, add; a project hides an organisation default and can add it
 * back). Registered on `orgAdminSections` / `projectAdminSections`. Changing the organisation's lists needs the Feedback
 * List Admin role; a project's needs the Feedback Triager role (the server decides, these panels render their controls).
 */
import { OrgTypeVocabularyPanel, ProjectTypeVocabularyPanel } from "../../components/TypeVocabularyPanels";
import { channelTypes, systemTypes } from "./api";

export function OrgExternalSystemsPanel({ orgId }: { orgId: string }) {
  return (
    <OrgTypeVocabularyPanel
      orgId={orgId} noun="External system" api={systemTypes.org}
      inUseMessage="This system is still used by a reference. Disable it instead of deleting it."
      description={
        <>
          The outside tools a request can point into — Jira, ServiceNow and the rest are seeded for a new organisation.
          Every project sees this list; a project may add its own or hide the ones it does not use.
        </>
      }
    />
  );
}

export function ProjectExternalSystemsPanel({ projectId }: { projectId: string }) {
  return (
    <ProjectTypeVocabularyPanel
      projectId={projectId} noun="External system" api={systemTypes.project}
      description={
        <>
          The external systems this project's requests can reference: the organisation's list plus any added for this
          project. A sub-project with no changes of its own shows its parent project's list; changing it here makes it
          its own. Hiding one only affects this project, and references already using it are kept.
        </>
      }
    />
  );
}

export function OrgRequestChannelsPanel({ orgId }: { orgId: string }) {
  return (
    <OrgTypeVocabularyPanel
      orgId={orgId} noun="Request channel" api={channelTypes.org}
      inUseMessage="This channel is still used by a project. Disable it instead of deleting it."
      description={
        <>
          How people ask for things — a support ticket, a call, an email. Each requester of a request can be given the
          channel they used, so you can see where demand comes from. Every project sees this list.
        </>
      }
    />
  );
}

export function ProjectRequestChannelsPanel({ projectId }: { projectId: string }) {
  return (
    <ProjectTypeVocabularyPanel
      projectId={projectId} noun="Request channel" api={channelTypes.project}
      description={
        <>
          The channels this project's requesters can be recorded as using: the organisation's list plus any added for
          this project. A sub-project with no changes of its own shows its parent project's list; changing it here makes
          it its own. Hiding one only affects this project, and choices already made are kept.
        </>
      }
    />
  );
}
