import type { Meta, StoryObj } from "@storybook/react-vite";
import { matchPath } from "react-router-dom";
import { expect } from "storybook/test";

import { buildNotification } from "../testing/storybook-helpers";
import appSource from "../App.tsx?raw";
import notificationTargetKinds from "./notificationTargetKinds.json";
import { CORE_TARGET_KIND_NAMES, notificationOpenPath, resolveNotificationTarget, resolveTargetKind } from "./notificationTargets";
import { installedModules } from "./registry";

const meta: Meta = { title: "Modules/NotificationTargets" };
export default meta;

type Story = StoryObj;

/**
 * Notification data that satisfies each target kind. A new kind must add its sample here, which is what makes the
 * route guard below cover it.
 */
const SAMPLES: Record<string, Parameters<typeof buildNotification>[0]> = {
  record: { entity_type: "requirement", entity_id: "r-1", project_id: "p-1" },
  delivery_status: { entity_type: "project_stage", entity_id: "s-1", project_id: "p-1" },
  project: { entity_type: null, entity_id: null, project_id: "p-1" },
  project_members: { entity_type: "user", entity_id: "u-1", project_id: "p-1" },
  organization: { entity_type: "organization", entity_id: "o-1", project_id: null },
  organization_files: { entity_type: "organization", entity_id: "o-1", project_id: null },
  policy: { entity_type: "policy", entity_id: "pol-1", project_id: null },
  report_run: { entity_type: "generated_report", entity_id: "run-1", project_id: null },
  preferences_security: { entity_type: null, entity_id: null, project_id: null },
  server_files: { entity_type: null, entity_id: null, project_id: null },
  detail: { entity_type: null, entity_id: null, project_id: null },
  project_compliance: { entity_type: "project_compliance", entity_id: "pc-1", project_id: "p-1" },
  standard: { entity_type: "compliance_standard", entity_id: "std-1", project_id: null },
};

/** Every route pattern the application mounts: the core `<Route path>` literals, then each module's routes. */
function mountedRoutePatterns(): string[] {
  const core = [...appSource.matchAll(/<Route\s+(?:key=\{[^}]*\}\s+)?path="([^"]+)"/g)].map((m) => m[1]);
  const modules = installedModules.flatMap((m) => [...(m.routes ?? []), ...(m.globalRoutes ?? [])]).map((r) => r.path);
  return [...core, ...modules].filter((path) => path !== "*" && path !== "/*");
}

/** The backend's vocabulary (`notificationTargetKinds.json`) and the frontend's resolvers cover the same kinds. */
export const EveryKindHasAResolver: Story = {
  render: () => <div>Target kinds</div>,
  play: async () => {
    const resolvable = new Set([
      ...CORE_TARGET_KIND_NAMES,
      ...installedModules.flatMap((m) => Object.keys(m.notificationTargets ?? {})),
    ]);
    await expect([...notificationTargetKinds].filter((kind) => !resolvable.has(kind))).toEqual([]);
    await expect([...resolvable].filter((kind) => !notificationTargetKinds.includes(kind))).toEqual([]);
    await expect(Object.keys(SAMPLES).sort()).toEqual([...notificationTargetKinds].sort());
  },
};

/** A renamed page cannot leave a dead link: each kind's address matches a mounted route. */
export const EveryKindOpensAMountedRoute: Story = {
  render: () => <div>Target routes</div>,
  play: async () => {
    const patterns = mountedRoutePatterns();
    const dead: string[] = [];
    for (const kind of notificationTargetKinds.filter((k) => k !== "detail")) {
      const path = resolveTargetKind(kind, buildNotification({ id: "n-1", target_kinds: [kind], ...SAMPLES[kind] }));
      if (path === null) dead.push(`${kind}: no page`);
      else if (!patterns.some((pattern) => matchPath({ path: pattern, end: true }, path))) dead.push(`${kind}: ${path}`);
    }
    await expect(dead).toEqual([]);
    await expect(patterns.some((pattern) => matchPath({ path: pattern, end: true }, notificationOpenPath({ id: "n-1" })))).toBe(true);
  },
};

/** The first kind a type lists that has its data wins; a notification with none falls to the detail page. */
export const TriesKindsInOrder: Story = {
  render: () => <div>Kind order</div>,
  play: async () => {
    const grant = ["standard", "organization", "project"];
    const open = (overrides: Parameters<typeof buildNotification>[0]) =>
      resolveNotificationTarget(buildNotification({ target_kinds: grant, ...overrides }));
    await expect(open({ entity_type: "compliance_standard", entity_id: "std-1", project_id: null })).toBe("/standards/std-1");
    await expect(open({ entity_type: "organization", entity_id: "o-1", project_id: null })).toBe("/orgs/o-1/overview");
    await expect(open({ entity_type: null, entity_id: null, project_id: "p-1" })).toBe("/projects/p-1");
    // A grant stored before the organisation id was recorded has nothing to open.
    await expect(open({ entity_type: null, entity_id: null, project_id: null })).toBeNull();
  },
};

/** The reported defect: a phase notification opens Delivery status, not project administration. */
export const StageNotificationsOpenDeliveryStatus: Story = {
  render: () => <div>Stage targets</div>,
  play: async () => {
    const stage = buildNotification({
      type: "stage_phase_overdue", target_kinds: ["delivery_status"], entity_type: "project_stage", entity_id: "s-1", project_id: "p-1",
    });
    await expect(resolveNotificationTarget(stage)).toBe("/projects/p-1/stage-phases");
  },
};

/** A module's record opens through its own `artefactPaths`, a core record through core's. */
export const RecordKindOpensTheRecord: Story = {
  render: () => <div>Record targets</div>,
  play: async () => {
    const record = (entity_type: string, project_id: string | null = "p-1") =>
      resolveNotificationTarget(buildNotification({ target_kinds: ["record"], entity_type, entity_id: "x-1", project_id }));
    await expect(record("risk")).toBe("/projects/p-1/modules/risk_management/risks/x-1");
    await expect(record("requirement")).toBe("/projects/p-1/requirements/x-1");
    await expect(record("change_request")).toBe("/projects/p-1/change-requests/x-1");
    await expect(record("not_a_type")).toBeNull();
    await expect(record("risk", null)).toBeNull();
  },
};

/** A background report opens its page whether the run belonged to a project or to the whole organisation. */
export const ReportRunsOpenTheirPage: Story = {
  render: () => <div>Report run targets</div>,
  play: async () => {
    const run = (project_id: string | null) =>
      resolveNotificationTarget(
        buildNotification({ target_kinds: ["report_run"], entity_type: "generated_report", entity_id: "run-1", project_id }),
      );
    await expect(run("p-1")).toBe("/report-runs/run-1");
    await expect(run(null)).toBe("/report-runs/run-1");
  },
};

/** A message with a page of its own, and one with none: the latter is the detail page, never a dead click. */
export const MessagesWithNoPageHaveNoTarget: Story = {
  render: () => <div>Detail targets</div>,
  play: async () => {
    await expect(resolveNotificationTarget(buildNotification({ target_kinds: ["detail"], entity_type: "announcement", entity_id: "a-1", project_id: null }))).toBeNull();
    await expect(resolveNotificationTarget(buildNotification({ target_kinds: [], project_id: "p-1" }))).toBeNull();
    await expect(notificationOpenPath({ id: "n-9" })).toBe("/notifications/n-9");
  },
};
