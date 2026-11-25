/**
 * Module: modules/product_feedback/FeedbackListPanels
 *
 * The admin screens of the module's classified list — the channels a requester can have asked through — as thin
 * wrappers over the shared `OrgTypeVocabularyPanel` and `ProjectTypeVocabularyPanel` (rename, reorder, disable, add; a
 * project hides an organisation default and can add it back). Registered on `orgAdminSections` /
 * `projectAdminSections`. Changing the organisation's list needs the Feedback List Admin role; a project's needs the
 * Feedback Triager role (the server decides, these panels render their controls). The external systems a request's
 * references can name are shared with every record type and administered in core settings (`ExternalSystemsPanels`).
 */
import { OrgTypeVocabularyPanel, ProjectTypeVocabularyPanel } from "../../components/TypeVocabularyPanels";
import { channelTypes } from "./api";

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
