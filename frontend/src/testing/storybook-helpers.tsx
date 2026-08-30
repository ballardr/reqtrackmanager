/**
 * Module: testing/storybook-helpers
 *
 * Shared fixtures and decorators for Storybook stories. Pages/components
 * under test talk to three things a bare render can't provide: the `api`
 * REST client (frontend/src/api/client.ts), `AuthContext`, and
 * `TerminologyContext`'s `ProjectContext` — this module is the one seam for
 * all three, so every story mocks them the same way instead of each file
 * reinventing fixture shapes or provider wiring.
 *
 * `api`'s methods are spied directly with `spyOn` from "storybook/test"
 * (re-exported from @vitest/spy) at each story's own `beforeEach`/`play`,
 * rather than through a bespoke wrapper here — `spyOn(api, "get")
 * .mockResolvedValue(...)` is already the whole primitive a story needs;
 * wrapping it would only add a layer with nothing of its own to say. This
 * module only provides what genuinely is shared: fixture data shapes and
 * the two context providers.
 */
import type { Decorator } from "@storybook/react-vite";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { AuthContext, type AuthContextValue } from "../context/AuthContextValue";
import { ProjectContext } from "../context/ProjectContextValue";
import { ToastProvider } from "../context/ToastContext";
import { StatefulAuthProvider } from "./StatefulAuthProvider";
import type {
  ActionTypeDefinition,
  Category,
  ChangeEntry,
  ChangeRequest,
  Comment,
  Component,
  FileAsset,
  LinkTypeDefinition,
  Notification,
  Project,
  ProjectFile,
  ProjectListItem,
  ProjectStage,
  ProjectStatusDefinition,
  Requirement,
  RequirementAction,
  RequirementLink,
  User,
} from "../api/types";

let idCounter = 0;
function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}-${idCounter}`;
}

export function buildUser(overrides: Partial<User> = {}): User {
  return {
    id: nextId("user"),
    email: "alex.morgan@example.com",
    display_name: "Alex Morgan",
    is_server_admin: false,
    is_active: true,
    landing_preference: "projects",
    theme_preference: "light",
    pronouns: null,
    avatar_file_id: null,
    display_name_locked: false,
    is_2fa_enabled: false,
    email_digest_mode: "instant",
    ui_preferences: {},
    ...overrides,
  };
}

export function buildProject(overrides: Partial<Project> = {}): Project {
  return {
    id: nextId("project"),
    organization_id: nextId("org"),
    name: "Atlas Platform",
    summary: "Core platform requirements for the Atlas programme.",
    created_at: "2026-01-05T09:00:00Z",
    updated_at: "2026-03-01T14:30:00Z",
    is_archived: false,
    is_template: false,
    allow_member_change_requests: true,
    visibility: "only_specified",
    terminology: {},
    status_id: "status-1",
    parent_project_id: null,
    role_inheritance_mode: "none",
    role_inheritance_filter_role: null,
    can_be_parent: false,
    ...overrides,
  };
}

export function buildProjectStatus(overrides: Partial<ProjectStatusDefinition> = {}): ProjectStatusDefinition {
  return { id: nextId("status"), organization_id: "org-1", name: "Active", sort_order: 0, ...overrides };
}

export function buildLinkType(overrides: Partial<LinkTypeDefinition> = {}): LinkTypeDefinition {
  return {
    id: nextId("linktype"), organization_id: "org-1", forward_name: "Depends on",
    reverse_name: "Is a dependency of", sort_order: 0, ...overrides,
  };
}

export function buildActionType(overrides: Partial<ActionTypeDefinition> = {}): ActionTypeDefinition {
  return { id: nextId("actiontype"), project_id: "project-1", name: "Review", sort_order: 0, ...overrides };
}

export function buildProjectListItem(overrides: Partial<ProjectListItem> = {}): ProjectListItem {
  return {
    ...buildProject(),
    current_stage_name: "Build",
    current_stage_status: "scoping",
    my_roles: ["project_manager"],
    is_favorite: false,
    organization_name: "Acme Corp",
    requirement_count: 24,
    children: [],
    ...overrides,
  };
}

export function buildStage(overrides: Partial<ProjectStage> = {}): ProjectStage {
  return {
    id: nextId("stage"),
    project_id: "project-1",
    name: "Build",
    status: "scoping",
    sort_order: 0,
    is_current: true,
    approved_at: null,
    completed_at: null,
    completed_by: null,
    review_deadline: null,
    ...overrides,
  };
}

export function buildComponent(overrides: Partial<Component> = {}): Component {
  return {
    id: nextId("component"),
    project_id: "project-1",
    name: "Authentication",
    prefix: "AUTH",
    sort_order: 0,
    ...overrides,
  };
}

export function buildCategory(overrides: Partial<Category> = {}): Category {
  return {
    id: nextId("category"),
    project_id: "project-1",
    component_id: "component-1",
    name: "Login",
    prefix: "LOG",
    sort_order: 0,
    ...overrides,
  };
}

export function buildRequirement(overrides: Partial<Requirement> = {}): Requirement {
  // `is_locked`/`requires_approval` derive from `status` by the same rule
  // the backend uses (`LOCKED_STATUSES`/`REQUIRES_APPROVAL_STATUSES`,
  // backend/app/services/requirements.py,
  // backend/app/routers/requirements.py) so a story only needs to set
  // `status` and gets a consistent, real derived state — rather than every
  // "approved" story call site having to separately remember to
  // also pass `is_locked: true` (2026-08 UX audit roadmap, "No requirement
  // approval action" — added when the Approve button/"Make change request"
  // gating started actually reading these two fields). An explicit override
  // for either still wins, via the trailing `...overrides` spread.
  //
  // C-G-11: completion (`is_completed`/`completed_at`/`completed_by`) is now
  // an independent overlay, not derived from `status` at all (unlike the
  // old "completed" status value this replaced) — a story that wants a
  // completed fixture must pass `is_completed: true` explicitly, same as
  // any other override.
  const status = overrides.status ?? "draft";
  return {
    id: nextId("requirement"),
    project_id: "project-1",
    unique_code: "AUTH-LOG-001",
    name: "Users can reset a forgotten password",
    reasoning: "Locked-out users need a self-service recovery path.",
    clarification: "",
    description: "A user who has forgotten their password can request a reset link by email.",
    status,
    owner_id: "user-1",
    component_id: "component-1",
    category_id: "category-1",
    target_stage_id: "stage-1",
    level: "requirement",
    sort_order: 0,
    creator_id: "user-1",
    is_archived: false,
    is_locked: status === "approved",
    is_completed: false,
    completed_at: null,
    completed_by: null,
    keywords: [],
    custom_fields: {},
    created_at: "2026-01-10T09:00:00Z",
    updated_at: "2026-01-10T09:00:00Z",
    is_subscribed: false,
    comment_count: 0,
    has_open_change_request: false,
    requires_approval: status === "draft" || status === "reviewed",
    review_date: null,
    review_lead_days: null,
    reviewer_id: null,
    ...overrides,
  };
}

export function buildRequirementLink(overrides: Partial<RequirementLink> = {}): RequirementLink {
  return {
    id: nextId("link"), source_requirement_id: "requirement-1", target_requirement_id: "requirement-2",
    link_type_id: "linktype-1", direction: "outgoing", display_name: "Depends on",
    other_requirement_id: "requirement-2", other_requirement_unique_code: "AUTH-LOG-002",
    other_requirement_name: "Users can enable two-factor authentication",
    ...overrides,
  };
}

export function buildRequirementAction(overrides: Partial<RequirementAction> = {}): RequirementAction {
  return {
    id: nextId("action"), project_id: "project-1", unique_code: "ACT-001", action_type_id: "actiontype-1",
    title: "Review password reset flow", description: "Confirm the reset link expiry window matches policy.",
    outcome_status: "pending", assignee_id: "user-1", due_date: "2026-04-01",
    completed_at: null, completed_by: null, creator_id: "user-1", is_archived: false,
    archived_at: null, archived_by: null, created_at: "2026-01-10T09:00:00Z", updated_at: "2026-01-10T09:00:00Z",
    comment_count: 0,
    ...overrides,
  };
}

export function buildFileAsset(overrides: Partial<FileAsset> = {}): FileAsset {
  return {
    id: nextId("file"), organization_id: "org-1", filename: "spec.pdf", content_type: "application/pdf",
    size_bytes: 10240, uploaded_by: "user-1", is_org_resource: false, created_at: "2026-01-10T09:00:00Z",
    ...overrides,
  };
}

/** `GET /projects/{id}/files` row (ProjectFilesPage) — defaults to a
 * requirement-attachment row; pass `source: "action_attachment"` (with
 * `action_id`/`action_unique_code`/`action_title`) or `"comment_attachment"`
 * (with `comment_id`, alongside the requirement fields) to build the other
 * two origin shapes. */
export function buildProjectFile(overrides: Partial<ProjectFile> = {}): ProjectFile {
  return {
    file: buildFileAsset(),
    uploaded_by_display_name: "Alex Morgan",
    source: "requirement_attachment",
    requirement_id: "requirement-1",
    requirement_unique_code: "SW-PERF-001",
    requirement_name: "Ship the widget",
    action_id: null,
    action_unique_code: null,
    action_title: null,
    comment_id: null,
    ...overrides,
  };
}

export function buildChangeRequest(overrides: Partial<ChangeRequest> = {}): ChangeRequest {
  return {
    id: nextId("cr"),
    project_id: "project-1",
    requirement_id: "requirement-1",
    kind: "modify_requirement",
    status: "draft",
    creator_id: "user-1",
    proposed_name: null,
    proposed_reasoning: null,
    proposed_clarification: null,
    proposed_description: null,
    proposed_target_stage_id: null,
    proposed_level: null,
    reason: "Clarify the reset link expiry window.",
    custom_fields: {},
    submitted_at: null,
    decided_at: null,
    decided_by: null,
    decision_note: "",
    created_at: "2026-02-01T09:00:00Z",
    is_subscribed: false,
    comment_count: 0,
    requires_approval: true,
    proposed_review_date: null,
    proposed_review_lead_days: null,
    proposed_reviewer_id: null,
    changed_fields: [],
    proposed_attachment_file_ids: [],
    proposed_action_link_id: null,
    proposed_action_title: null,
    proposed_action_description: null,
    proposed_action_type_id: null,
    proposed_action_assignee_id: null,
    proposed_action_due_date: null,
    ...overrides,
  };
}

export function buildComment(overrides: Partial<Comment> = {}): Comment {
  return {
    id: nextId("comment"),
    author_id: "user-1",
    author_display_name: "Alex Morgan",
    body: "Looks good to me.",
    created_at: "2026-02-02T10:00:00Z",
    edited_at: null,
    reaction_count: 0,
    reacted_by_me: false,
    attachments: [],
    ...overrides,
  };
}

export function buildNotification(overrides: Partial<Notification> = {}): Notification {
  return {
    id: nextId("notification"),
    type: "comment_added",
    title: "New comment",
    body: "Alex Morgan commented on AUTH-LOG-001",
    project_id: "project-1",
    entity_type: "requirement",
    entity_id: "requirement-1",
    created_at: "2026-02-02T10:00:00Z",
    read_at: null,
    ...overrides,
  };
}

export function buildChangeEntry(overrides: Partial<ChangeEntry> = {}): ChangeEntry {
  return {
    timestamp: "2026-02-02T10:00:00Z",
    entity_type: "requirement",
    entity_id: "requirement-1",
    action: "updated",
    actor_id: "user-1",
    actor_display_name: "Alex Morgan",
    detail: null,
    ...overrides,
  };
}

/** Wraps a story in `AuthContext` with a fixture (or logged-out) user —
 * `null` matches `AuthProvider`'s own "not logged in" state. Action
 * functions default to throwing so an unmocked call fails loudly in a
 * story's `play` function rather than silently resolving `undefined`. */
export function withAuth(user: User | null, overrides: Partial<AuthContextValue> = {}): Decorator {
  const value: AuthContextValue = {
    user,
    loading: false,
    login: async () => {
      throw new Error("login() was not mocked for this story");
    },
    signup: async () => {
      throw new Error("signup() was not mocked for this story");
    },
    verify2fa: async () => {
      throw new Error("verify2fa() was not mocked for this story");
    },
    logout: () => {},
    refreshUser: async () => {},
    setUiPreference: () => {},
    ...overrides,
  };
  return (Story) => (
    <AuthContext.Provider value={value}>
      <Story />
    </AuthContext.Provider>
  );
}

/**
 * Like `withAuth`, but with a real, stateful `setUiPreference` — needed for
 * any story that exercises a `useUiPreference`-backed control (view-mode
 * toggles, collapsible sections, the nav rail's collapse button, ...) and
 * asserts the resulting UI actually changes, not just that the callback
 * fired. `withAuth`'s `setUiPreference` is a no-op by design (most stories
 * don't need it); this is the one seam where a story does.
 */
export function withStatefulAuth(initialUser: User, overrides: Partial<AuthContextValue> = {}): Decorator {
  return (Story) => (
    <StatefulAuthProvider initialUser={initialUser} overrides={overrides}>
      <Story />
    </StatefulAuthProvider>
  );
}

/** Wraps a story in `TerminologyContext`'s `ProjectContext` with fixed term
 * overrides, bypassing the real per-project fetch effect. */
export function withTerminology(terminology: Record<string, string> = {}): Decorator {
  return (Story) => (
    <ProjectContext.Provider value={{ terminology }}>
      <Story />
    </ProjectContext.Provider>
  );
}

/**
 * Wraps a story in a `MemoryRouter`, starting at `initialPath`. Pass
 * `routePath` (e.g. `/projects/:projectId/requirements/:requirementId`)
 * for pages that read `useParams` — defaults to a catch-all for pages that
 * only need `useNavigate`/`<Link>` to work, not real param extraction.
 */
export function withRouter(initialPath: string, routePath = "*"): Decorator {
  return (Story) => (
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route path={routePath} element={<Story />} />
      </Routes>
    </MemoryRouter>
  );
}

/** Wraps a story in a real `ToastProvider` — for any page/component whose
 * play function asserts a toast appears after a mutation (`useToast()`
 * throws outside a provider, same as every other context hook here). */
export function withToast(): Decorator {
  return (Story) => (
    <ToastProvider>
      <Story />
    </ToastProvider>
  );
}
