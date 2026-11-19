/**
 * Module: modules/notificationTargets
 *
 * The one resolver that turns a notification into the page it opens. The bell, the notification list and the email
 * all open `/notifications/:id` (`NotificationOpenPage`), which calls `resolveNotificationTarget` here, so no surface
 * carries its own route table and a notification can never open a different page depending on where it was clicked.
 *
 * Responsibilities:
 * - Resolve each core target kind the backend's `services/notification_targets.py` declares (a record, Delivery status,
 *   a project, an organisation, a policy, a report run, a preference page...).
 * - Resolve a module's own kind through `TierAModuleDefinition.notificationTargets`, so core never names a module's page.
 * - Try the kinds a type lists in order; the first that finds the data it needs in the notification wins.
 *
 * Design decisions: a kind is a name, not a URL, so a renamed page changes one function here (and
 * `notificationTargets.stories.tsx` fails if any kind opens no route). A stored notification created before a kind
 * existed lacks its data and falls through to the detail page rather than opening a wrong one. `detail` is never
 * returned: it means "show the message", which only the page that calls this can do.
 */
import type { Notification } from "../api/types";
import { getArtefactPath } from "./artefactPaths";
import { installedModules } from "./registry";

type TargetResolver = (n: Notification) => string | null;

/** Whether the notification names the organisation, project or other entity of `type` it was created with. */
function entityOf(n: Notification, type: string): string | null {
  return n.entity_type === type && n.entity_id ? n.entity_id : null;
}

/** Core's target kinds; keep in step with `CORE_TARGET_KINDS` in `backend/app/services/notification_targets.py`. */
const CORE_TARGETS: Record<string, TargetResolver> = {
  record: (n) =>
    n.project_id && n.entity_type && n.entity_id ? getArtefactPath(n.entity_type, n.project_id, n.entity_id) : null,
  delivery_status: (n) => (n.project_id ? `/projects/${n.project_id}/stage-phases` : null),
  project: (n) => (n.project_id ? `/projects/${n.project_id}` : null),
  project_members: (n) => (n.project_id ? `/projects/${n.project_id}/admin/members` : null),
  organization: (n) => {
    const id = entityOf(n, "organization");
    return id ? `/orgs/${id}/overview` : null;
  },
  organization_files: (n) => {
    const id = entityOf(n, "organization");
    return id ? `/orgs/${id}/files` : null;
  },
  policy: (n) => {
    const id = entityOf(n, "policy");
    return id ? `/policies/${id}` : null;
  },
  report_run: (n) => {
    const id = entityOf(n, "generated_report");
    return id ? `/report-runs/${id}` : null;
  },
  preferences_security: () => "/preferences/security",
  server_files: () => "/server/management/files",
  // The notification's own page; opened by `NotificationOpenPage` when nothing else applies.
  detail: () => null,
};

/** The core kinds, so a guard can check each opens a route. */
export const CORE_TARGET_KIND_NAMES: string[] = Object.keys(CORE_TARGETS);

/** The page a target kind opens for this notification: core's resolver, else the module that declares the kind. */
export function resolveTargetKind(kind: string, n: Notification): string | null {
  const core = CORE_TARGETS[kind];
  if (core) return core(n);
  for (const module of installedModules) {
    const resolver = module.notificationTargets?.[kind];
    if (resolver) return resolver(n);
  }
  return null;
}

/**
 * The page a notification opens: the first of its type's kinds that has what it needs, or `null` when none does (the
 * notification detail page then shows the message itself).
 *
 * @param n The notification, with the target kinds its type declares.
 */
export function resolveNotificationTarget(n: Notification): string | null {
  for (const kind of n.target_kinds) {
    const path = resolveTargetKind(kind, n);
    if (path) return path;
  }
  return null;
}

/** The address every surface opens for a notification: the detail route, which resolves and navigates. */
export function notificationOpenPath(n: Pick<Notification, "id">): string {
  return `/notifications/${n.id}`;
}
